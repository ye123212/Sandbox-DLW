#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, Optional
from urllib import error, request


def http_json(base_url: str, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    headers: Dict[str, str] = {}
    body: Optional[bytes] = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")

    req = request.Request(url=url, method=method.upper(), headers=headers, data=body)

    try:
        with request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} on {method.upper()} {path}: {err_body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Failed to connect to {url}: {exc}") from exc


def assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_in(actual: Any, expected_values: tuple[Any, ...], label: str) -> None:
    if actual not in expected_values:
        raise AssertionError(f"{label}: expected one of {expected_values!r}, got {actual!r}")


def run_smoke_test(base_url: str, repo_path: str, session_id: str) -> None:
    print(f"Using session_id={session_id}")

    print("[1/5] Checking /health")
    health = http_json(base_url, "GET", "/health")
    assert_equal(health.get("status"), "ok", "health.status")
    print("PASS: health check")

    print("[2/5] Evaluating safe file-read action")
    safe_action = {
        "action_type": "file_read",
        "description": "Read README for context",
        "target_path": "README.md",
        "changed_files": [],
        "repo_path": repo_path,
        "session_id": session_id,
    }
    safe_result = http_json(base_url, "POST", "/api/v1/evaluate-action", safe_action)
    safe_gate = (safe_result.get("reversibility") or {}).get("gate")
    assert_in(safe_gate, ("auto_execute", "log_and_execute"), "safe_action.gate")
    print(f"PASS: safe action gate={safe_gate}")

    print("[3/5] Evaluating blocked destructive shell action")
    blocked_action = {
        "action_type": "shell",
        "description": "Dangerous recursive delete",
        "command": "rm -rf ./tmp",
        "changed_files": [],
        "repo_path": repo_path,
        "session_id": session_id,
    }
    blocked_result = http_json(base_url, "POST", "/api/v1/evaluate-action", blocked_action)
    blocked_gate = (blocked_result.get("reversibility") or {}).get("gate")
    assert_equal(blocked_gate, "block", "blocked_action.gate")
    print("PASS: destructive command is blocked")

    print("[4/5] Proposing human-gated action")
    human_gate_action = {
        "action_type": "shell",
        "description": "Push branch to remote",
        "command": "git push origin main",
        "changed_files": [],
        "repo_path": repo_path,
        "session_id": session_id,
    }
    proposal = http_json(base_url, "POST", "/api/v1/gates/propose", human_gate_action)
    assert_equal(proposal.get("execution_mode"), "pending", "proposal.execution_mode")
    gate_status = proposal.get("gate_status") or {}
    assert_equal(gate_status.get("status"), "pending", "proposal.gate_status.status")
    gate_id = str(gate_status.get("gate_id") or "")
    if not gate_id:
        raise AssertionError("proposal.gate_status.gate_id: missing gate id")
    print(f"PASS: human gate pending (gate_id={gate_id})")

    print("[5/5] Rejecting pending gate via decision API")
    decision = http_json(
        base_url,
        "POST",
        f"/api/v1/gates/{gate_id}/decision",
        {"decision": "reject", "note": "Smoke test cleanup"},
    )
    decision_status = (decision.get("gate_status") or {}).get("status")
    assert_equal(decision_status, "rejected", "decision.gate_status.status")
    print("PASS: gate decision recorded as rejected")

    print("All smoke tests passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentShield API smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="AgentShield API base URL")
    parser.add_argument("--repo-path", default=".", help="Repository path sent in payloads")
    parser.add_argument(
        "--session-id",
        default="",
        help="Session ID to use (defaults to testbench-smoke-<timestamp>)",
    )
    args = parser.parse_args()

    session_id = args.session_id or f"testbench-smoke-{int(time.time())}"

    try:
        run_smoke_test(base_url=args.base_url, repo_path=args.repo_path, session_id=session_id)
        return 0
    except Exception as exc:
        print(f"Smoke test failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

