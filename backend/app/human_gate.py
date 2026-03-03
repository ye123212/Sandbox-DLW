from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import time
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class GateStatus(BaseModel):
    gate_id: str
    status: Literal["pending", "approved", "rejected"]
    reason: str
    action: Dict[str, Any]
    evaluation: Dict[str, Any]
    created_at: float
    decided_at: Optional[float] = None


class GateProposalResponse(BaseModel):
    execution_mode: Literal["immediate", "pending", "denied"]
    gate_status: GateStatus


class GateDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: Optional[str] = None


class GateDecisionResponse(BaseModel):
    gate_status: GateStatus


@dataclass
class PendingGate:
    gate_id: str
    status: Literal["pending", "approved", "rejected"]
    reason: str
    action: Dict[str, Any]
    evaluation: Dict[str, Any]
    created_at: float
    decided_at: Optional[float] = None

    def to_model(self) -> GateStatus:
        return GateStatus(
            gate_id=self.gate_id,
            status=self.status,
            reason=self.reason,
            action=self.action,
            evaluation=self.evaluation,
            created_at=self.created_at,
            decided_at=self.decided_at,
        )


class HumanGateManager:
    def __init__(self) -> None:
        self._lock = Lock()
        self._items: Dict[str, PendingGate] = {}

    def propose(self, action: Dict[str, Any], evaluation: Dict[str, Any]) -> GateProposalResponse:
        gate = (
            evaluation.get("reversibility", {}).get("gate")
            if isinstance(evaluation, dict)
            else None
        )
        reason = (
            evaluation.get("reversibility", {}).get("reason")
            if isinstance(evaluation, dict)
            else "No reason available."
        )
        now = time()
        gate_id = str(uuid4())

        if gate in ("auto_execute", "log_and_execute"):
            item = PendingGate(
                gate_id=gate_id,
                status="approved",
                reason=reason or "Auto-approved by policy.",
                action=action,
                evaluation=evaluation,
                created_at=now,
                decided_at=now,
            )
            with self._lock:
                self._items[gate_id] = item
            return GateProposalResponse(execution_mode="immediate", gate_status=item.to_model())

        if gate == "require_human":
            item = PendingGate(
                gate_id=gate_id,
                status="pending",
                reason=reason or "Human approval required.",
                action=action,
                evaluation=evaluation,
                created_at=now,
            )
            with self._lock:
                self._items[gate_id] = item
            return GateProposalResponse(execution_mode="pending", gate_status=item.to_model())

        item = PendingGate(
            gate_id=gate_id,
            status="rejected",
            reason=reason or "Blocked by policy.",
            action=action,
            evaluation=evaluation,
            created_at=now,
            decided_at=now,
        )
        with self._lock:
            self._items[gate_id] = item
        return GateProposalResponse(execution_mode="denied", gate_status=item.to_model())

    def decide(self, gate_id: str, decision: GateDecisionRequest) -> GateDecisionResponse:
        with self._lock:
            if gate_id not in self._items:
                raise KeyError(f"gate_id={gate_id} not found")
            item = self._items[gate_id]
            if item.status != "pending":
                return GateDecisionResponse(gate_status=item.to_model())

            if decision.decision == "approve":
                item.status = "approved"
                item.reason = decision.note or "Approved by human operator."
            else:
                item.status = "rejected"
                item.reason = decision.note or "Rejected by human operator."
            item.decided_at = time()
            self._items[gate_id] = item
            return GateDecisionResponse(gate_status=item.to_model())

    def get(self, gate_id: str) -> Optional[GateStatus]:
        with self._lock:
            item = self._items.get(gate_id)
        return item.to_model() if item else None

    def list_pending(self, session_id: Optional[str] = None) -> List[GateStatus]:
        with self._lock:
            pending = []
            for item in self._items.values():
                if item.status != "pending":
                    continue
                if session_id is not None and str(item.action.get("session_id", "default")) != session_id:
                    continue
                pending.append(item.to_model())
        pending.sort(key=lambda item: item.created_at, reverse=True)
        return pending
