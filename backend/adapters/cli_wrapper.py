from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.adapters.base import BaseAgentAdapter


class CLIAdapter(BaseAgentAdapter):
    def normalize_action(self, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "action_type": raw_event["action_type"],
            "description": raw_event["description"],
            "command": raw_event.get("command"),
            "target_path": raw_event.get("target_path"),
            "changed_files": raw_event.get("changed_files", []),
            "repo_path": raw_event.get("repo_path", self.repo_path),
            "session_id": raw_event.get("session_id", self.session_id),
        }

    def execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        action_type = action["action_type"]
        if action_type == "shell":
            return self._run_shell(action["command"])
        if action_type == "sql":
            return self._simulate_sql(action["command"])
        if action_type in ("file_write", "file_modify"):
            return self._write_file(action["target_path"], action.get("command") or "")
        if action_type == "file_read":
            return self._read_file(action["target_path"])
        return {"message": "No executor configured for this action type."}

    def run_shell(
        self,
        command: str,
        description: Optional[str] = None,
        changed_files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        event = {
            "action_type": "shell",
            "description": description or f"Run shell command: {command}",
            "command": command,
            "changed_files": changed_files or [],
            "repo_path": self.repo_path,
            "session_id": self.session_id,
        }
        return self.run_with_shield(event)

    def run_sql(self, sql: str, description: Optional[str] = None) -> Dict[str, Any]:
        event = {
            "action_type": "sql",
            "description": description or "Execute SQL command",
            "command": sql,
            "repo_path": self.repo_path,
            "session_id": self.session_id,
        }
        return self.run_with_shield(event)

    def write_file(self, target_path: str, content: str, is_modify: bool = True) -> Dict[str, Any]:
        event = {
            "action_type": "file_modify" if is_modify else "file_write",
            "description": f"{'Modify' if is_modify else 'Write'} file {target_path}",
            "command": content,
            "target_path": target_path,
            "changed_files": [target_path],
            "repo_path": self.repo_path,
            "session_id": self.session_id,
        }
        return self.run_with_shield(event)

    def read_file(self, target_path: str) -> Dict[str, Any]:
        event = {
            "action_type": "file_read",
            "description": f"Read file {target_path}",
            "target_path": target_path,
            "repo_path": self.repo_path,
            "session_id": self.session_id,
        }
        return self.run_with_shield(event)

    def _run_shell(self, command: str) -> Dict[str, Any]:
        process = subprocess.run(
            command,
            shell=True,
            cwd=self.repo_path,
            text=True,
            capture_output=True,
        )
        return {
            "returncode": process.returncode,
            "stdout": process.stdout[-4000:],
            "stderr": process.stderr[-4000:],
        }

    def _simulate_sql(self, sql: str) -> Dict[str, Any]:
        return {"status": "simulated", "sql": sql}

    def _write_file(self, target_path: str, content: str) -> Dict[str, Any]:
        if not target_path:
            raise ValueError("target_path is required for write actions")
        path = Path(self.repo_path) / target_path
        old_content = None
        if path.exists():
            try:
                old_content = path.read_text("utf-8")
            except Exception:
                old_content = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return {"status": "written", "path": str(path), "bytes": len(content.encode("utf-8")), "old_content": old_content}
        except OSError as exc:
            return {"status": "error", "error": f"Failed to write file: {exc}"}

    def _read_file(self, target_path: Optional[str]) -> Dict[str, Any]:
        if not target_path:
            raise ValueError("target_path is required for read actions")
        path = Path(self.repo_path) / target_path
        if not path.exists():
            return {"status": "error", "error": f"File not found: {target_path}"}
        if not path.is_file():
            return {"status": "error", "error": f"Not a file: {target_path}"}
        try:
            text = path.read_text(encoding="utf-8")
            return {"status": "read", "path": str(path), "content": text[:4000]}
        except (UnicodeDecodeError, OSError) as exc:
            return {"status": "error", "error": f"Failed to read file: {exc}"}
