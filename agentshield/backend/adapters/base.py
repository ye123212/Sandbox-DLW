from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib import error, request


class AgentShieldClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000") -> None:
        self.base_url = base_url.rstrip("/")

    def evaluate_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/api/v1/evaluate-action", action)

    def propose_gate(self, action: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/api/v1/gates/propose", action)

    def get_gate(self, gate_id: str) -> Dict[str, Any]:
        return self._get(f"/api/v1/gates/{gate_id}")

    def decide_gate(self, gate_id: str, decision: str, note: Optional[str] = None) -> Dict[str, Any]:
        payload = {"decision": decision}
        if note:
            payload["note"] = note
        return self._post(f"/api/v1/gates/{gate_id}/decision", payload)

    def publish_event(
        self,
        event_type: str,
        message: str,
        session_id: str = "default",
        level: str = "info",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "session_id": session_id,
            "event_type": event_type,
            "level": level,
            "message": message,
            "data": data or {},
        }
        return self._post("/api/v1/events", payload)

    def wait_for_gate_decision(
        self,
        gate_id: str,
        timeout_seconds: int = 300,
        poll_interval_seconds: float = 1.5,
    ) -> Dict[str, Any]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            gate = self.get_gate(gate_id)
            status = gate.get("status")
            if status in ("approved", "rejected"):
                return gate
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for gate decision: {gate_id}")

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        req = request.Request(url, method="GET")
        try:
            with request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"AgentShield GET failed ({exc.code}): {body}") from exc

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"AgentShield POST failed ({exc.code}): {body}") from exc


class BaseAgentAdapter(ABC):
    def __init__(
        self,
        shield_client: Optional[AgentShieldClient] = None,
        repo_path: str = ".",
        session_id: str = "default",
        on_gate_pending: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self.shield = shield_client or AgentShieldClient()
        self.repo_path = str(Path(repo_path))
        self.session_id = session_id
        self.on_gate_pending = on_gate_pending

    @abstractmethod
    def normalize_action(self, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def run_with_shield(self, raw_event: Dict[str, Any], wait_timeout_seconds: int = 300) -> Dict[str, Any]:
        action = self.normalize_action(raw_event)
        action["repo_path"] = action.get("repo_path") or self.repo_path
        action["session_id"] = action.get("session_id") or self.session_id
        session_id = str(action["session_id"])
        action_preview = {
            "action_type": action.get("action_type"),
            "description": action.get("description"),
            "command": action.get("command"),
            "target_path": action.get("target_path"),
        }
        self.shield.publish_event(
            event_type="action.proposed",
            message=f"Proposed action: {action.get('action_type')} - {action.get('description')}",
            session_id=session_id,
            data={"action": action_preview},
        )

        proposed = self.shield.propose_gate(action)
        mode = proposed.get("execution_mode")
        gate_status = proposed.get("gate_status", {})
        gate_id = gate_status.get("gate_id", "")

        if mode == "denied":
            self.shield.publish_event(
                event_type="action.denied",
                message=f"Action denied by policy: {action.get('action_type')}",
                session_id=session_id,
                level="warn",
                data={"gate_id": gate_id, "reason": gate_status.get("reason")},
            )
            return {
                "status": "denied",
                "gate_id": gate_id,
                "reason": gate_status.get("reason", "Action denied by AgentShield."),
                "action": action,
                "evaluation": gate_status.get("evaluation"),
            }

        if mode == "pending":
            self.shield.publish_event(
                event_type="gate.pending",
                message=f"Human approval required for {action.get('action_type')}",
                session_id=session_id,
                level="warn",
                data={"gate_id": gate_id, "reason": gate_status.get("reason")},
            )
            if self.on_gate_pending:
                self.on_gate_pending(gate_id, proposed)
            gate_status = self.shield.wait_for_gate_decision(gate_id, timeout_seconds=wait_timeout_seconds)
            if gate_status.get("status") != "approved":
                self.shield.publish_event(
                    event_type="gate.rejected",
                    message=f"Human rejected action: {action.get('action_type')}",
                    session_id=session_id,
                    level="warn",
                    data={"gate_id": gate_id, "reason": gate_status.get("reason")},
                )
                return {
                    "status": "denied",
                    "gate_id": gate_id,
                    "reason": gate_status.get("reason", "Rejected by human operator."),
                    "action": action,
                    "evaluation": gate_status.get("evaluation"),
                }
            self.shield.publish_event(
                event_type="gate.approved",
                message=f"Human approved action: {action.get('action_type')}",
                session_id=session_id,
                data={"gate_id": gate_id, "reason": gate_status.get("reason")},
            )

        execution = self.execute_action(action)
        self.shield.publish_event(
            event_type="action.executed",
            message=f"Action executed: {action.get('action_type')}",
            session_id=session_id,
            data={"gate_id": gate_id, "result_summary": str(execution)[:400]},
        )
        return {
            "status": "executed",
            "gate_id": gate_id,
            "action": action,
            "execution": execution,
            "evaluation": gate_status.get("evaluation"),
        }
