# AgentShield (Base v0)

Base implementation of **AgentShield** focused on the first 2 pillars from `final_idea.md`:

1. **Reversibility Classification**
2. **Blast Radius Estimation**

This version is implemented as:
- A FastAPI backend for action evaluation
- An embeddable popup/panel overlay (`agentshield-overlay.js`) that can sit on top of existing coding-agent UIs (Codex/Cursor/Devin-like host pages)

## What is implemented

### 1) Reversibility Classification
- Rule-based scoring across ~30 operation patterns (file, git, SQL, shell)
- Gate outputs:
  - `auto_execute`
  - `log_and_execute`
  - `require_human`
  - `block`
- Destructive patterns are blocked (e.g., `DROP TABLE`, `rm -rf`, `git reset --hard`)
- Unknown/ambiguous shell/SQL actions can be classified by LLM fallback (`GEMINI_API_KEY` + Gemini model)
- Decision thresholds are configurable per session (`auto_execute_threshold`, `log_execute_threshold`, `block_threshold`)

### 2) Blast Radius Estimation
- Builds a Python dependency graph using `ast` imports
- Traverses reverse dependencies to estimate impacted files/modules
- Detects SQL table references from action text/command using regex
- Returns summary with:
  - `affected_files`
  - `affected_modules`
  - `affected_tables`
  - impacted file paths + referenced tables

## Project structure

- `backend/app/main.py`: FastAPI app + analysis logic
- `backend/app/human_gate.py`: In-memory human approval queue service
- `backend/adapters/base.py`: Shared AgentShield client + adapter contract
- `backend/adapters/tool_wrapper.py`: Tool-call adapter wrapper
- `backend/adapters/cli_wrapper.py`: CLI/shell/file/sql adapter wrapper
- `frontend/agentshield-overlay.js`: Embeddable control panel overlay
- `frontend/demo-host.html`: Example host coding-agent UI with AgentShield overlay on top
- `requirements.txt`: Python deps

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
```

Open:
- Demo chat page: `http://127.0.0.1:8000/`
- Health: `http://127.0.0.1:8000/health`

## How to embed on an existing agent UI

Add to your host page:

```html
<script>
  window.AgentShieldConfig = { apiBaseUrl: "http://127.0.0.1:8000" };
</script>
<script src="http://127.0.0.1:8000/static/agentshield-overlay.js"></script>
```

To programmatically evaluate an action from your agent loop:

```js
window.AgentShieldOverlay.open();
window.AgentShieldOverlay.evaluateAction({
  action_type: "sql",
  description: "Alter users table to add index",
  command: "ALTER TABLE users ADD COLUMN region TEXT;",
  target_path: "backend/app/main.py",
  changed_files: ["backend/app/main.py"],
  repo_path: "."
});
```

## Notes

- This base version intentionally focuses only on the first two pillars.
- Pillars 3-5 (intent drift, adversarial review, rollback timeline) are not yet implemented.
- LLM fallback is optional. If `GEMINI_API_KEY` is not set, unknown commands fall back to conservative threshold policy.

## Adapter usage (real agent integration scaffold)

### 1) Tool wrapper

```python
from backend.adapters.tool_wrapper import ToolAdapter

adapter = ToolAdapter(repo_path=".")

@adapter.shielded_tool(tool_name="run_sql", action_type="sql", command_builder=lambda kw: kw["query"])
def run_sql(query: str) -> dict:
    return {"ok": True, "query": query}

result = run_sql(query="ALTER TABLE users ADD COLUMN region TEXT;")
print(result)
```

### 2) CLI wrapper

```python
from backend.adapters.cli_wrapper import CLIAdapter

adapter = CLIAdapter(repo_path=".")
result = adapter.run_shell("git status")
print(result)
```

### 3) Human gate API endpoints

- `POST /api/v1/gates/propose` (auto-eval + gate proposal)
- `GET /api/v1/gates/pending` (pending approvals for panel)
- `GET /api/v1/gates/{gate_id}` (status polling)
- `POST /api/v1/gates/{gate_id}/decision` (approve/reject)

### 3.5) Live event feed endpoints (for floating panel)

- `POST /api/v1/events` (publish runtime event)
- `GET /api/v1/events?session_id=default&after_seq=0&limit=50` (poll incremental events)

### 3.6) Chat endpoint (real prompt -> tool inference -> AgentShield)

- `POST /api/v1/chat/run`
  - Input: `prompt`, `provider` (`gemini` or `openai`), `session_id`, `model`, `max_steps`, `repo_path`
  - Output: final assistant text
  - The model infers tool use (`read_file`, `run_shell`, `write_file`); AgentShield intercepts and gates every tool execution.

### 4) Session policy endpoints (Pillar 1 thresholds)

- `GET /api/v1/sessions/{session_id}/policy`
- `PUT /api/v1/sessions/{session_id}/policy`

Example:

```bash
curl -X PUT "http://127.0.0.1:8000/api/v1/sessions/demo/policy" \
  -H "Content-Type: application/json" \
  -d '{
    "auto_execute_threshold": 0.9,
    "log_execute_threshold": 0.65,
    "block_threshold": 0.2,
    "enable_llm_fallback": true,
    "llm_model": "gemini-2.5-flash"
  }'
```

## Step 1: Minimal real agent loop (OpenAI API + AgentShield)

This script runs a real tool-calling loop and gates every tool execution through AgentShield.

File:
- `backend/examples/minimal_agent_loop.py`

Setup env (OpenAI):

```bash
export OPENAI_API_KEY="your_key_here"
export OPENAI_MODEL="gpt-4o-mini"
export AGENTSHIELD_URL="http://127.0.0.1:8000"
```

Run AgentShield API first:

```bash
uvicorn backend.app.main:app --reload
```

In another terminal, run the minimal orchestrator:

```bash
python3 -m backend.examples.minimal_agent_loop --prompt "Read README.md and summarize the implemented pillars."
```

Setup env (Gemini):

```bash
export GEMINI_API_KEY="your_gemini_key"
export GEMINI_MODEL="gemini-2.5-flash"
export AGENTSHIELD_URL="http://127.0.0.1:8000"
```

Run with Gemini:

```bash
python3 -m backend.examples.minimal_agent_loop \
  --provider gemini \
  --model "$GEMINI_MODEL" \
  --session-id "demo-live" \
  --prompt "Read README.md and summarize the implemented pillars."
```

Notes:
- If the model proposes a risky action (`require_human`), the script waits for approval.
- Approve/reject from the overlay panel (Pending Human Gates) or via gate decision endpoint.
- You can set `AGENTSHIELD_SESSION_ID` or pass `--session-id` to run different threshold policies per session.
- In the built-in chat demo (`/`), set the `Session ID` input to match the panel session so live activity aligns.
- Set `repo_path` (via UI input) to the repository you want blast-radius analysis against.

Run with OpenAI:

```bash
export OPENAI_API_KEY="your_openai_key"
```

In the chat UI (`/`):
- Set provider input to `openai`
- Set model input to `gpt-4o-mini` (or another tool-capable OpenAI model)
