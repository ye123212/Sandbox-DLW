from __future__ import annotations

import ast
import base64
import json
import os
import re
import shutil
import time
import zipfile
from dataclasses import dataclass
from collections import defaultdict, deque
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
from urllib import error, request
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from backend.app.agent_runtime import run_agent, timeline_store, intent_store
from backend.app.human_gate import (
    GateDecisionRequest,
    GateDecisionResponse,
    GateProposalResponse,
    GateStatus,
    HumanGateManager,
)


class ProposedAction(BaseModel):
    action_type: Literal["file_read", "file_write", "file_modify", "shell", "sql", "other"]
    description: str
    command: Optional[str] = None
    target_path: Optional[str] = None
    changed_files: List[str] = Field(default_factory=list)
    repo_path: str = "."
    session_id: str = "default"


class ReversibilityResult(BaseModel):
    score: float
    gate: Literal["auto_execute", "log_and_execute", "require_human", "block"]
    reason: str
    operation: str = "unknown"
    classifier: Literal["rules", "llm_fallback", "default"] = "default"


class SessionPolicy(BaseModel):
    auto_execute_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    log_execute_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    block_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    enable_llm_fallback: bool = True
    llm_provider: Literal["auto", "openai", "gemini"] = "auto"
    llm_model: str = "gpt-4o-mini"

    @model_validator(mode="after")
    def validate_thresholds(self) -> "SessionPolicy":
        if not (self.block_threshold <= self.log_execute_threshold <= self.auto_execute_threshold):
            raise ValueError(
                "Thresholds must satisfy: block_threshold <= log_execute_threshold <= auto_execute_threshold"
            )
        return self


class SessionPolicyResponse(BaseModel):
    session_id: str
    policy: SessionPolicy


class EventIn(BaseModel):
    session_id: str = "default"
    event_type: str
    level: Literal["info", "warn", "error"] = "info"
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)


class EventRecord(EventIn):
    seq: int
    timestamp: float


class EventListResponse(BaseModel):
    events: List[EventRecord]
    last_seq: int


class ChatRunRequest(BaseModel):
    prompt: str
    session_id: str = "default"
    model: str = "gemini-2.5-flash"
    max_steps: int = Field(default=6, ge=1, le=20)
    repo_path: str = "."
    provider: Literal["openai", "gemini"] = "gemini"


class ChatRunResponse(BaseModel):
    session_id: str
    final_text: str
    steps_used: int


class RepoUploadResponse(BaseModel):
    repo_id: str
    repo_path: str
    file_count: int
    message: str


class RepoUploadJsonRequest(BaseModel):
    filename: str
    zip_base64: str


class BlastRadiusResult(BaseModel):
    affected_files: int
    affected_modules: int
    affected_tables: int
    impacted_file_paths: List[str]
    referenced_tables: List[str]
    summary: str


class EvaluateResponse(BaseModel):
    reversibility: ReversibilityResult
    blast_radius: BlastRadiusResult

class ActionCheckpoint(BaseModel):
    id: str
    timestamp: float
    action_type: str
    description: str
    risk_score: float
    reversible: bool
    diffs: Dict[str, str] = Field(default_factory=dict)
    inverse_command: Optional[str] = None
    drift_score: float = 1.0
    repo_path: str = "."

class RollbackRequest(BaseModel):
    checkpoint_id: str


class SessionPolicyStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._store: Dict[str, SessionPolicy] = {"default": SessionPolicy()}

    def get(self, session_id: str) -> SessionPolicy:
        with self._lock:
            return self._store.get(session_id, self._store["default"])

    def set(self, session_id: str, policy: SessionPolicy) -> SessionPolicy:
        with self._lock:
            self._store[session_id] = policy
            return policy


class EventStore:
    def __init__(self, max_events_per_session: int = 500) -> None:
        self._lock = Lock()
        self._events_by_session: Dict[str, deque[EventRecord]] = defaultdict(deque)
        self._seq = 0
        self._max = max_events_per_session

    def append(self, event: EventIn) -> EventRecord:
        with self._lock:
            self._seq += 1
            seq = self._seq
        record = EventRecord(seq=seq, timestamp=time.time(), **event.model_dump())
        with self._lock:
            bucket = self._events_by_session[event.session_id]
            bucket.append(record)
            while len(bucket) > self._max:
                bucket.popleft()
        return record

    def list(self, session_id: str, after_seq: int = 0, limit: int = 100) -> EventListResponse:
        with self._lock:
            bucket = list(self._events_by_session.get(session_id, deque()))
            last_seq = self._seq
        filtered = [evt for evt in bucket if evt.seq > after_seq]
        if limit > 0:
            filtered = filtered[-limit:]
        return EventListResponse(events=filtered, last_seq=last_seq)


class RepoStore:
    def __init__(self, base_dir: Path) -> None:
        self._lock = Lock()
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._repos: Dict[str, Path] = {}

    def register_zip(self, upload_name: str, zip_bytes: bytes) -> RepoUploadResponse:
        repo_id = str(uuid4())
        repo_dir = (self.base_dir / repo_id).resolve()
        repo_dir.mkdir(parents=True, exist_ok=True)

        zip_path = repo_dir / (upload_name or "repo.zip")
        zip_path.write_bytes(zip_bytes)

        extracted_root = repo_dir / "repo"
        extracted_root.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                members = zf.infolist()
                if not members:
                    raise ValueError("Zip archive is empty.")
                for member in members:
                    extracted_target = (extracted_root / member.filename).resolve()
                    if not str(extracted_target).startswith(str(extracted_root.resolve())):
                        raise ValueError("Zip contains invalid path traversal entries.")
                zf.extractall(path=extracted_root)
        except (zipfile.BadZipFile, ValueError) as exc:
            shutil.rmtree(repo_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"Invalid zip upload: {exc}") from exc

        candidates = [p for p in extracted_root.iterdir() if p.name != "__MACOSX"]
        actual_repo_root = extracted_root
        if len(candidates) == 1 and candidates[0].is_dir():
            actual_repo_root = candidates[0]

        with self._lock:
            self._repos[repo_id] = actual_repo_root

        file_count = sum(1 for p in actual_repo_root.rglob("*") if p.is_file())
        return RepoUploadResponse(
            repo_id=repo_id,
            repo_path=str(actual_repo_root),
            file_count=file_count,
            message="Repository uploaded and extracted.",
        )

class GraphCache:
    def __init__(self) -> None:
        self._cache: Dict[str, Tuple[float, Dict[str, Set[str]], Dict[str, Set[str]], Dict[str, Path]]] = {}

    def get_or_build(
        self, repo_path: Path
    ) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]], Dict[str, Path]]:
        repo_key = str(repo_path.resolve())
        latest_mtime = self._scan_latest_mtime(repo_path)
        cached = self._cache.get(repo_key)
        if cached and cached[0] >= latest_mtime:
            return cached[1], cached[2], cached[3]

        graph, reverse_graph, module_to_path = self._build_dependency_graph(repo_path)
        self._cache[repo_key] = (latest_mtime, graph, reverse_graph, module_to_path)
        return graph, reverse_graph, module_to_path

    def _scan_latest_mtime(self, repo_path: Path) -> float:
        latest = 0.0
        for path in repo_path.rglob("*.py"):
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:
                continue
        return latest

    def _build_dependency_graph(
        self, repo_path: Path
    ) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]], Dict[str, Path]]:
        module_to_path: Dict[str, Path] = {}
        for py_file in repo_path.rglob("*.py"):
            try:
                rel_parts = py_file.relative_to(repo_path).parts
            except ValueError:
                continue
            if ".venv" in rel_parts or "node_modules" in rel_parts:
                continue
            rel = py_file.relative_to(repo_path).with_suffix("")
            module_name = ".".join(rel.parts)
            module_to_path[module_name] = py_file

        graph: Dict[str, Set[str]] = defaultdict(set)
        reverse_graph: Dict[str, Set[str]] = defaultdict(set)

        for module_name, py_file in module_to_path.items():
            imports = self._extract_imports(py_file)
            for imported in imports:
                if imported in module_to_path:
                    graph[module_name].add(imported)
                    reverse_graph[imported].add(module_name)

        return graph, reverse_graph, module_to_path

    def _extract_imports(self, py_file: Path) -> Set[str]:
        imports: Set[str] = set()
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception:
            return imports

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        return imports


graph_cache = GraphCache()
gate_manager = HumanGateManager()
policy_store = SessionPolicyStore()
event_store = EventStore()
repo_store = RepoStore(base_dir=Path(".agentshield_uploads").resolve())
app = FastAPI(title="AgentShield Base API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass(frozen=True)
class ReversibilityRule:
    name: str
    pattern: str
    score: float
    reason: str
    applies_to: Tuple[str, ...]
    target: Literal["command", "description", "path", "combined"] = "combined"
    hard_gate: Optional[Literal["auto_execute", "log_and_execute", "require_human", "block"]] = None


def gate_from_score(
    score: float, policy: SessionPolicy
) -> Literal["auto_execute", "log_and_execute", "require_human", "block"]:
    if score <= policy.block_threshold:
        return "block"
    if score < policy.log_execute_threshold:
        return "require_human"
    if score < policy.auto_execute_threshold:
        return "log_and_execute"
    return "auto_execute"


REVERSIBILITY_RULES: List[ReversibilityRule] = [
    ReversibilityRule("file_read", r".*", 1.0, "Read-only file access.", ("file_read",), target="description"),
    ReversibilityRule("file_write_new", r".*", 0.8, "Writing new file is usually reversible.", ("file_write",), target="description"),
    ReversibilityRule("file_modify", r".*", 0.5, "Existing file changes should be logged.", ("file_modify",), target="description"),
    ReversibilityRule("rm_recursive", r"\brm\s+-rf\b", 0.0, "Recursive delete is destructive.", ("shell",), hard_gate="block"),
    ReversibilityRule("file_delete", r"\b(delete|remove|unlink)\b", 0.2, "File deletion risks data loss.", ("shell", "other")),
    ReversibilityRule("file_move", r"\b(mv|rename|move)\b", 0.65, "File moves are reversible with care.", ("shell", "other")),
    ReversibilityRule("file_copy", r"\b(cp|copy)\b", 0.8, "Copy operation is reversible.", ("shell", "other")),
    ReversibilityRule("chmod", r"\bchmod\b", 0.45, "Permission changes can break runtime behavior.", ("shell",)),
    ReversibilityRule("chown", r"\bchown\b", 0.35, "Ownership changes may require human review.", ("shell",)),
    ReversibilityRule("list_directory", r"\b(ls|find|tree|dir)\b", 0.95, "Read-only directory inspection.", ("shell",)),
    ReversibilityRule("search_text", r"\b(rg|grep|ack)\b", 0.95, "Read-only text search.", ("shell",)),
    ReversibilityRule("view_file", r"\b(cat|head|tail|less|sed\s+-n)\b", 0.95, "Read-only file view.", ("shell",)),
    ReversibilityRule("git_status", r"\bgit\s+status\b", 0.95, "Read-only git status.", ("shell",)),
    ReversibilityRule("git_diff", r"\bgit\s+(diff|show|log)\b", 0.92, "Read-only git inspection.", ("shell",)),
    ReversibilityRule("git_add", r"\bgit\s+add\b", 0.75, "Staging is reversible.", ("shell",)),
    ReversibilityRule("git_restore", r"\bgit\s+restore\b", 0.55, "Restore may discard local changes.", ("shell",)),
    ReversibilityRule("git_commit", r"\bgit\s+commit\b", 0.72, "Commit is reversible but history-mutating.", ("shell",)),
    ReversibilityRule("git_switch", r"\bgit\s+(checkout|switch)\b", 0.5, "Branch switches can alter worktree state.", ("shell",)),
    ReversibilityRule("git_merge", r"\bgit\s+(merge|rebase|cherry-pick)\b", 0.3, "History merge/rebase is risky.", ("shell",), hard_gate="require_human"),
    ReversibilityRule("git_revert", r"\bgit\s+revert\b", 0.68, "Revert is usually safe but affects history.", ("shell",)),
    ReversibilityRule("git_reset_soft", r"\bgit\s+reset\s+--(soft|mixed)\b", 0.35, "Reset can discard index/work changes.", ("shell",)),
    ReversibilityRule("git_reset_hard", r"\bgit\s+reset\s+--hard\b", 0.0, "Hard reset is destructive.", ("shell",), hard_gate="block"),
    ReversibilityRule("git_clean", r"\bgit\s+clean\s+-[fdx]+\b", 0.0, "Git clean deletes untracked files.", ("shell",), hard_gate="block"),
    ReversibilityRule("git_push", r"\bgit\s+push\b", 0.25, "Remote side effects require human review.", ("shell",), hard_gate="require_human"),
    ReversibilityRule("git_pull", r"\bgit\s+pull\b", 0.55, "Pull can merge/rewrite local state.", ("shell",)),
    ReversibilityRule("install_pkg", r"\b(pip|pip3|npm|yarn|pnpm|brew|apt|apt-get)\s+install\b", 0.45, "Package installation changes environment.", ("shell",)),
    ReversibilityRule("docker_build", r"\bdocker\s+build\b", 0.7, "Build is mostly reversible.", ("shell",)),
    ReversibilityRule("docker_run", r"\bdocker\s+run\b", 0.5, "Runtime side effects depend on mounts/network.", ("shell",)),
    ReversibilityRule("curl_exec", r"\b(curl|wget).*(\|\s*(sh|bash)|>\s*/tmp/)", 0.1, "Remote script execution is high risk.", ("shell",), hard_gate="block"),
    ReversibilityRule("dd_disk", r"\bdd\s+if=", 0.0, "Raw disk writes are destructive.", ("shell",), hard_gate="block"),
    ReversibilityRule("mkfs", r"\bmkfs\b", 0.0, "Filesystem formatting is irreversible.", ("shell",), hard_gate="block"),
    ReversibilityRule("shutdown", r"\b(shutdown|reboot)\b", 0.1, "Host availability impact is high.", ("shell",), hard_gate="require_human"),
    ReversibilityRule("sql_select", r"\bselect\b", 0.95, "Read-only SQL query.", ("sql",)),
    ReversibilityRule("sql_explain", r"\bexplain\b", 0.95, "Read-only query plan.", ("sql",)),
    ReversibilityRule("sql_insert", r"\binsert\s+into\b", 0.55, "Data insert mutates state.", ("sql",)),
    ReversibilityRule("sql_update", r"\bupdate\b", 0.4, "Update statements mutate existing data.", ("sql",)),
    ReversibilityRule("sql_delete_where", r"\bdelete\s+from\b.+\bwhere\b", 0.3, "Delete with filter is risky.", ("sql",)),
    ReversibilityRule("sql_delete_all", r"\bdelete\s+from\b(?!.*\bwhere\b)", 0.05, "Bulk delete without WHERE is destructive.", ("sql",), hard_gate="block"),
    ReversibilityRule("sql_create_table", r"\bcreate\s+table\b", 0.5, "Schema creation can be reverted with migration.", ("sql",)),
    ReversibilityRule("sql_alter_table", r"\balter\s+table\b", 0.2, "Schema mutation is high impact.", ("sql",), hard_gate="require_human"),
    ReversibilityRule("sql_drop_or_truncate", r"\b(drop\s+table|truncate)\b", 0.0, "Irreversible SQL operation detected.", ("sql",), hard_gate="block"),
    ReversibilityRule("sql_create_index", r"\bcreate\s+index\b", 0.52, "Index creation is generally reversible.", ("sql",)),
]


def _rule_target_text(action: ProposedAction, target: Literal["command", "description", "path", "combined"]) -> str:
    cmd = (action.command or "").lower()
    desc = action.description.lower()
    path = (action.target_path or "").lower()
    if target == "command":
        return cmd
    if target == "description":
        return desc
    if target == "path":
        return path
    return "\n".join([cmd, desc, path])


def _llm_fallback_reversibility(action: ProposedAction, policy: SessionPolicy) -> Optional[ReversibilityResult]:
    llm_provider = policy.llm_provider
    if llm_provider == "auto":
        llm_provider = "openai" if os.getenv("OPENAI_API_KEY") else "gemini"
    llm_model = policy.llm_model
    if llm_provider == "openai" and llm_model.startswith("gemini"):
        llm_model = "gpt-4o-mini"
    if llm_provider == "gemini" and llm_model.startswith("gpt-"):
        llm_model = "gemini-2.5-flash"

    if llm_provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        payload = {
            "model": llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a safety classifier for AI coding agent actions. "
                        "Return strict JSON with keys: operation, score, suggested_gate, reason, confidence. "
                        "score must be 0.0-1.0. suggested_gate must be one of auto_execute, log_and_execute, require_human, block."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "action_type": action.action_type,
                            "description": action.description,
                            "command": action.command,
                            "target_path": action.target_path,
                            "changed_files": action.changed_files,
                        }
                    ),
                },
            ],
        }
        req = request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=25) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                parsed = json.loads(raw["choices"][0]["message"]["content"])
        except (error.URLError, error.HTTPError, KeyError, ValueError, json.JSONDecodeError):
            return None
    else:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
        model_name = llm_model.strip()
        if model_name.startswith("models/"):
            model_name = model_name.split("/", 1)[1]
        prompt = (
            "You are a safety classifier for AI coding agent actions.\n"
            "Return STRICT JSON only with keys: operation, score, suggested_gate, reason, confidence.\n"
            "score must be 0.0-1.0. suggested_gate must be one of auto_execute, log_and_execute, require_human, block.\n"
            "Input action follows:\n"
            f"{json.dumps({'action_type': action.action_type, 'description': action.description, 'command': action.command, 'target_path': action.target_path, 'changed_files': action.changed_files})}"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=25) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                candidates = raw.get("candidates") or []
                parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
                content = ""
                for part in parts:
                    if part.get("text"):
                        content = part["text"]
                        break
                if not content:
                    return None
                parsed = json.loads(content)
        except (error.URLError, error.HTTPError, KeyError, ValueError, json.JSONDecodeError):
            return None

    score = float(parsed.get("score", 0.4))
    score = min(1.0, max(0.0, score))
    gate = parsed.get("suggested_gate")
    if gate not in ("auto_execute", "log_and_execute", "require_human", "block"):
        gate = gate_from_score(score, policy)
    return ReversibilityResult(
        score=score,
        gate=gate,
        reason=str(parsed.get("reason", "LLM fallback classification.")),
        operation=str(parsed.get("operation", "llm_classified")),
        classifier="llm_fallback",
    )


def classify_reversibility(action: ProposedAction, policy: SessionPolicy) -> ReversibilityResult:
    for rule in REVERSIBILITY_RULES:
        if action.action_type not in rule.applies_to:
            continue
        text = _rule_target_text(action, rule.target)
        if re.search(rule.pattern, text, flags=re.IGNORECASE):
            gate = rule.hard_gate or gate_from_score(rule.score, policy)
            return ReversibilityResult(
                score=rule.score,
                gate=gate,
                reason=rule.reason,
                operation=rule.name,
                classifier="rules",
            )

    if action.action_type in ("shell", "sql", "other") and policy.enable_llm_fallback:
        fallback = _llm_fallback_reversibility(action, policy)
        if fallback is not None:
            return fallback

    default_score = 0.4
    return ReversibilityResult(
        score=default_score,
        gate=gate_from_score(default_score, policy),
        reason="Unclassified action. Defaulting to conservative threshold policy.",
        operation="default_unknown",
        classifier="default",
    )


SQL_TABLE_PATTERN = re.compile(
    r"\b(from|join|update|into|table|alter\s+table|drop\s+table)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    flags=re.IGNORECASE,
)


def to_module(repo_path: Path, file_path: Path) -> Optional[str]:
    try:
        rel = file_path.resolve().relative_to(repo_path.resolve()).with_suffix("")
        return ".".join(rel.parts)
    except Exception:
        return None


def estimate_blast_radius(action: ProposedAction) -> BlastRadiusResult:
    repo_path = Path(action.repo_path).resolve()
    if not repo_path.exists():
        repo_path = Path(".").resolve()

    _, reverse_graph, module_to_path = graph_cache.get_or_build(repo_path)
    module_to_file = {module: str(path) for module, path in module_to_path.items()}

    impacted_modules: Set[str] = set()
    queue: deque[str] = deque()

    changed = action.changed_files.copy()
    if action.target_path:
        changed.append(action.target_path)

    for raw_path in changed:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (repo_path / candidate).resolve()
        module_name = to_module(repo_path, candidate)
        if module_name and module_name in module_to_path:
            impacted_modules.add(module_name)
            queue.append(module_name)

    while queue:
        current = queue.popleft()
        for dependent in reverse_graph.get(current, set()):
            if dependent not in impacted_modules:
                impacted_modules.add(dependent)
                queue.append(dependent)

    candidate_text = " ".join(filter(None, [action.description, action.command]))
    referenced_tables = sorted({match[1].lower() for match in SQL_TABLE_PATTERN.findall(candidate_text)})
    impacted_paths = sorted(module_to_file[module] for module in impacted_modules if module in module_to_file)

    affected_files = len(impacted_paths)
    affected_modules = len({module.split(".")[0] for module in impacted_modules})
    affected_tables = len(referenced_tables)

    summary = (
        f"This action may impact {affected_files} files across {affected_modules} modules "
        f"and references {affected_tables} SQL tables."
    )

    return BlastRadiusResult(
        affected_files=affected_files,
        affected_modules=affected_modules,
        affected_tables=affected_tables,
        impacted_file_paths=impacted_paths,
        referenced_tables=referenced_tables,
        summary=summary,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/sessions/{session_id}/policy", response_model=SessionPolicyResponse)
def get_session_policy(session_id: str) -> SessionPolicyResponse:
    return SessionPolicyResponse(session_id=session_id, policy=policy_store.get(session_id))


@app.put("/api/v1/sessions/{session_id}/policy", response_model=SessionPolicyResponse)
def put_session_policy(session_id: str, policy: SessionPolicy) -> SessionPolicyResponse:
    stored = policy_store.set(session_id, policy)
    return SessionPolicyResponse(session_id=session_id, policy=stored)


@app.post("/api/v1/evaluate-action", response_model=EvaluateResponse)
def evaluate_action(action: ProposedAction) -> EvaluateResponse:
    policy = policy_store.get(action.session_id)
    reversibility = classify_reversibility(action, policy)
    blast_radius = estimate_blast_radius(action)
    event_store.append(
        EventIn(
            session_id=action.session_id,
            event_type="action.evaluated",
            message=f"Evaluated action: {action.action_type}",
            data={
                "action_type": action.action_type,
                "gate": reversibility.gate,
                "score": reversibility.score,
                "operation": reversibility.operation,
                "classifier": reversibility.classifier,
                "blast_summary": blast_radius.summary,
                "affected_files": blast_radius.affected_files,
                "affected_modules": blast_radius.affected_modules,
                "affected_tables": blast_radius.affected_tables,
            },
        )
    )
    return EvaluateResponse(reversibility=reversibility, blast_radius=blast_radius)


@app.post("/api/v1/gates/propose", response_model=GateProposalResponse)
def propose_gate(action: ProposedAction) -> GateProposalResponse:
    evaluation = evaluate_action(action).model_dump()
    proposed = gate_manager.propose(action.model_dump(), evaluation)
    event_store.append(
        EventIn(
            session_id=action.session_id,
            event_type="gate.proposed",
            level="warn" if proposed.execution_mode == "pending" else "info",
            message=f"Gate proposal: {proposed.execution_mode}",
            data={
                "action_type": action.action_type,
                "execution_mode": proposed.execution_mode,
                "gate_id": proposed.gate_status.gate_id,
                "reason": proposed.gate_status.reason,
            },
        )
    )
    return proposed


@app.get("/api/v1/gates/pending", response_model=List[GateStatus])
def list_pending_gates(session_id: Optional[str] = None) -> List[GateStatus]:
    return gate_manager.list_pending(session_id=session_id)


@app.get("/api/v1/gates/{gate_id}", response_model=GateStatus)
def get_gate(gate_id: str) -> GateStatus:
    gate = gate_manager.get(gate_id)
    if gate is None:
        raise HTTPException(status_code=404, detail="Gate not found")
    return gate


@app.post("/api/v1/gates/{gate_id}/decision", response_model=GateDecisionResponse)
def decide_gate(gate_id: str, decision: GateDecisionRequest) -> GateDecisionResponse:
    try:
        result = gate_manager.decide(gate_id, decision)
        gate = result.gate_status
        event_store.append(
            EventIn(
                session_id=str(gate.action.get("session_id", "default")),
                event_type="gate.decision",
                level="warn" if decision.decision == "reject" else "info",
                message=f"Gate {decision.decision}d: {gate_id}",
                data={"gate_id": gate_id, "decision": decision.decision, "note": decision.note},
            )
        )
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/events", response_model=EventRecord)
def publish_event(event: EventIn) -> EventRecord:
    return event_store.append(event)


@app.get("/api/v1/events", response_model=EventListResponse)
def list_events(
    session_id: str = "default",
    after_seq: int = 0,
    limit: int = 50,
) -> EventListResponse:
    safe_limit = min(max(limit, 1), 200)
    return event_store.list(session_id=session_id, after_seq=after_seq, limit=safe_limit)


@app.post("/api/v1/repos/upload", response_model=RepoUploadResponse)
def upload_repo_zip(payload: RepoUploadJsonRequest) -> RepoUploadResponse:
    if not payload.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Please upload a .zip repository archive.")
    try:
        data = base64.b64decode(payload.zip_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 zip payload.") from exc
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Zip too large (max 50MB).")
    return repo_store.register_zip(upload_name=payload.filename, zip_bytes=data)


@app.post("/api/v1/chat/run", response_model=ChatRunResponse)
def chat_run(payload: ChatRunRequest) -> ChatRunResponse:
    try:
        final_text, steps = run_agent(
            prompt=payload.prompt,
            session_id=payload.session_id,
            provider=payload.provider,
            model=payload.model,
            max_steps=payload.max_steps,
            repo_path=payload.repo_path,
        )
        return ChatRunResponse(session_id=payload.session_id, final_text=final_text, steps_used=steps)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/api/v1/sessions/{session_id}/timeline")
def get_timeline(session_id: str):
    return timeline_store.get_timeline(session_id)

@app.post("/api/v1/sessions/{session_id}/rollback")
def rollback_session(session_id: str, payload: RollbackRequest):
    timeline = timeline_store.get_timeline(session_id)
    idx = -1
    for i, chk in enumerate(timeline):
        if chk.id == payload.checkpoint_id:
            idx = i
            break
    if idx == -1:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
        
    actions_to_revert = timeline[idx+1:]
    actions_to_revert.reverse()
    
    for chk in actions_to_revert:
        repo_path = Path(chk.repo_path).resolve()
        for fp, old_content in chk.diffs.items():
            path = (repo_path / fp).resolve()
            if old_content is None:
                if path.exists():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(old_content, encoding="utf-8")
                
        # Remove reverted checkpoint
        timeline_store._store[session_id].remove(chk)
        
    return {"status": "ok", "reverted_count": len(actions_to_revert)}

@app.get("/")
def demo_root() -> FileResponse:
    return FileResponse(frontend_dir / "demo-host.html")
