from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List
from urllib import error, request

from backend.adapters.cli_wrapper import CLIAdapter


OPENAI_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command in the current repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    },
]


def call_openai_chat(
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.2,
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        OPENAI_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error ({exc.code}): {err_body}") from exc


def _openai_to_gemini_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    declarations: List[Dict[str, Any]] = []
    for t in tools:
        fn = t.get("function", {})
        declarations.append(
            {
                "name": fn.get("name"),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return [{"functionDeclarations": declarations}]


def call_gemini_chat(
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
) -> Dict[str, Any]:
    contents: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role in ("system", "user", "assistant"):
            text = m.get("content") or ""
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": text}]})
            if role == "assistant":
                for tc in m.get("tool_calls", []) or []:
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    contents.append(
                        {
                            "role": "model",
                            "parts": [{"functionCall": {"name": fn.get("name"), "args": args}}],
                        }
                    )
        elif role == "tool":
            try:
                payload = json.loads(m.get("content") or "{}")
            except json.JSONDecodeError:
                payload = {"raw": m.get("content")}
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": m.get("name", "tool_result"),
                                "response": {"content": payload},
                            }
                        }
                    ],
                }
            )

    payload = {
        "contents": contents,
        "tools": _openai_to_gemini_tools(tools),
        "generationConfig": {"temperature": 0.2},
    }

    url = f"{GEMINI_URL}/{model}:generateContent?key={api_key}"
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API error ({exc.code}): {err_body}") from exc


def parse_openai_response(resp: Dict[str, Any]) -> Dict[str, Any]:
    msg = resp["choices"][0]["message"]
    return {
        "content": msg.get("content", ""),
        "tool_calls": msg.get("tool_calls", []),
    }


def parse_gemini_response(resp: Dict[str, Any]) -> Dict[str, Any]:
    candidate = (resp.get("candidates") or [{}])[0]
    parts = ((candidate.get("content") or {}).get("parts") or [])
    text_chunks: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    for idx, part in enumerate(parts):
        if "text" in part and part["text"]:
            text_chunks.append(part["text"])
        if "functionCall" in part:
            fc = part["functionCall"]
            tool_calls.append(
                {
                    "id": f"gemini_fc_{idx}",
                    "type": "function",
                    "function": {
                        "name": fc.get("name"),
                        "arguments": json.dumps(fc.get("args", {})),
                    },
                }
            )
    return {"content": "\n".join(text_chunks).strip(), "tool_calls": tool_calls}


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal AgentShield-gated agent loop.")
    parser.add_argument(
        "--prompt",
        default="Read README.md and summarize what this project currently implements.",
    )
    parser.add_argument("--provider", choices=["auto", "openai", "gemini"], default="auto")
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL") or os.getenv("GEMINI_MODEL") or "gpt-4o-mini",
    )
    parser.add_argument(
        "--shield-url",
        default=os.getenv("AGENTSHIELD_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument("--session-id", default=os.getenv("AGENTSHIELD_SESSION_ID", "default"))
    parser.add_argument("--repo-path", default=".")
    parser.add_argument("--max-steps", type=int, default=6)
    args = parser.parse_args()

    provider = args.provider
    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    if provider == "auto":
        provider = "openai" if openai_key else "gemini" if gemini_key else "openai"

    if provider == "openai":
        if not openai_key:
            raise RuntimeError("OPENAI_API_KEY is not set. Use OPENAI_API_KEY or run with --provider gemini.")
        api_key = openai_key
    else:
        if not gemini_key:
            raise RuntimeError("GEMINI_API_KEY is not set. Use GEMINI_API_KEY or run with --provider openai.")
        api_key = gemini_key

    def on_gate_pending(gate_id: str, proposal: Dict[str, Any]) -> None:
        reason = proposal.get("gate_status", {}).get("reason", "")
        print(f"[AgentShield] Pending human approval. gate_id={gate_id} reason={reason}")
        print("Approve/reject from the AgentShield panel or call /api/v1/gates/{gate_id}/decision")

    adapter = CLIAdapter(
        repo_path=args.repo_path,
        session_id=args.session_id,
        on_gate_pending=on_gate_pending,
    )
    adapter.shield.base_url = args.shield_url.rstrip("/")
    adapter.shield.publish_event(
        event_type="agent.session_start",
        message="Agent session started.",
        session_id=args.session_id,
        data={"provider": provider, "model": args.model},
    )

    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a coding assistant. Use tools when needed. "
                "Keep actions minimal and prefer read-only operations first."
            ),
        },
        {"role": "user", "content": args.prompt},
    ]

    for step in range(1, args.max_steps + 1):
        if provider == "openai":
            response = call_openai_chat(api_key=api_key, model=args.model, messages=messages, tools=TOOLS)
            parsed = parse_openai_response(response)
        else:
            response = call_gemini_chat(api_key=api_key, model=args.model, messages=messages, tools=TOOLS)
            parsed = parse_gemini_response(response)

        tool_calls = parsed.get("tool_calls", [])

        if not tool_calls:
            final_text = parsed.get("content", "")
            print(f"\n[Assistant Final]\n{final_text}\n")
            adapter.shield.publish_event(
                event_type="agent.final",
                message="Agent produced final response.",
                session_id=args.session_id,
                data={"text_preview": final_text[:300]},
            )
            return

        messages.append(
            {
                "role": "assistant",
                "content": parsed.get("content") or "",
                "tool_calls": tool_calls,
            }
        )

        print(f"\n[Step {step}] Model requested {len(tool_calls)} tool call(s).")
        adapter.shield.publish_event(
            event_type="agent.tool_calls",
            message=f"Model requested {len(tool_calls)} tool call(s).",
            session_id=args.session_id,
            data={"step": step, "count": len(tool_calls)},
        )
        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            raw_args = tc["function"].get("arguments") or "{}"
            parsed_args = json.loads(raw_args)

            if tool_name == "run_shell":
                command = parsed_args["command"]
                result = adapter.run_shell(
                    command=command,
                    description=f"Agent requested shell command: {command}",
                )
            elif tool_name == "read_file":
                path = parsed_args["path"]
                result = adapter.read_file(path)
            else:
                result = {"status": "error", "error": f"Unsupported tool: {tool_name}"}

            print(f"- Tool `{tool_name}` result status: {result.get('status')}")
            adapter.shield.publish_event(
                event_type="agent.tool_result",
                message=f"Tool `{tool_name}` completed with status `{result.get('status')}`.",
                session_id=args.session_id,
                level="warn" if result.get("status") == "denied" else "info",
                data={"step": step, "tool_name": tool_name, "status": result.get("status")},
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tool_name,
                    "content": json.dumps(result),
                }
            )

    print("\n[Agent Loop] Max steps reached before final answer.")


if __name__ == "__main__":
    main()
