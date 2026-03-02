from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Dict, Optional

from backend.adapters.base import BaseAgentAdapter


class ToolAdapter(BaseAgentAdapter):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._tool_fn: Optional[Callable[..., Any]] = None

    def normalize_action(self, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "action_type": raw_event.get("action_type", "other"),
            "description": raw_event.get("description", "Tool invocation"),
            "command": raw_event.get("command"),
            "target_path": raw_event.get("target_path"),
            "changed_files": raw_event.get("changed_files", []),
            "repo_path": raw_event.get("repo_path", self.repo_path),
            "session_id": raw_event.get("session_id", self.session_id),
        }

    def execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        if self._tool_fn is None:
            raise RuntimeError("Tool function is not set")

        kwargs = action.get("_tool_kwargs", {})
        result = self._tool_fn(**kwargs)
        return {"result": result}

    def shielded_tool(
        self,
        tool_name: str,
        action_type: str = "other",
        command_builder: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
        description_builder: Optional[Callable[[Dict[str, Any]], str]] = None,
        target_path_builder: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
        changed_files_builder: Optional[Callable[[Dict[str, Any]], list[str]]] = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Dict[str, Any]]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Dict[str, Any]]:
            @wraps(func)
            def wrapped(**kwargs: Any) -> Dict[str, Any]:
                self._tool_fn = func
                event: Dict[str, Any] = {
                    "action_type": action_type,
                    "description": (
                        description_builder(kwargs)
                        if description_builder
                        else f"Tool `{tool_name}` called with args: {kwargs}"
                    ),
                    "command": command_builder(kwargs) if command_builder else None,
                    "target_path": target_path_builder(kwargs) if target_path_builder else None,
                    "changed_files": changed_files_builder(kwargs) if changed_files_builder else [],
                    "_tool_kwargs": kwargs,
                    "repo_path": self.repo_path,
                    "session_id": self.session_id,
                }
                return self.run_with_shield(event)

            return wrapped

        return decorator
