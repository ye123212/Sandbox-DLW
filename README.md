# AgentShield

AgentShield is a FastAPI safety gateway for coding agents. It evaluates proposed actions before execution, estimates blast radius, and routes risky actions through human approval.

## What this project includes

- `backend/app/main.py`: API server with reversibility classifier, blast-radius estimator, session policy APIs, gate APIs, event feed, chat endpoint, and rollback endpoint.
- `backend/adapters/`: Agent integration wrappers (`CLIAdapter`, `ToolAdapter`, base client).
- `backend/examples/minimal_agent_loop.py`: Minimal real tool-calling loop gated by AgentShield.
- `frontend/demo-host.html` + `frontend/agentshield-overlay.js`: Demo host page with AgentShield floating panel.
- `demo-repo/`: Small sample repository used for demos.
- `testbench/`: Smoke-test files and step-by-step verification guide.

## Prerequisites

- Python `3.10+`
- `pip`
- Optional (only for live LLM runs):
  - `OPENAI_API_KEY`
  - `GEMINI_API_KEY`

## Dependencies

This project currently installs:

- `fastapi==0.116.1`
- `uvicorn==0.35.0`

Install all dependencies with:

```powershell
pip install -r requirements.txt
```

## Setup

Run from the project root (`agentshield/`).

### PowerShell (Windows)
```powershell
$env:OPENAI_API_KEY="your_key"

```

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Bash (macOS/Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the project

Start the API server:

```powershell
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

Then open:

- Demo UI: `http://127.0.0.1:8000/`

## Key API routes

- `POST /api/v1/evaluate-action`
- `POST /api/v1/gates/propose`
- `GET /api/v1/gates/pending`
- `POST /api/v1/gates/{gate_id}/decision`
- `GET /api/v1/events`
- `PUT /api/v1/sessions/{session_id}/policy`
- `POST /api/v1/chat/run`
- `POST /api/v1/repos/upload`

## Run the included testbench

A testbench quick run (with API already running):

```powershell
python testbench/smoke_test.py --base-url http://127.0.0.1:8000 --repo-path .
```

## Optional: Minimal real agent loop

If you want to run the live tool-calling example in `backend/examples/minimal_agent_loop.py`:

### OpenAI example

```powershell
$env:OPENAI_API_KEY="your_key"
python -m backend.examples.minimal_agent_loop --provider openai --model gpt-4o-mini --repo-path .
```
Expected outcome when ran:

  The script starts an agent session in terminal.
  It sends a default (or provided) prompt to OpenAI.
  The model may request tool calls (read_file, run_shell).
  Every tool call is checked by AgentShield before execution.
  Terminal shows:
  step-by-step tool requests,
  whether actions were executed/denied/pending approval,
  and a final assistant response.
  If a risky action needs approval, it pauses until human decision is made via AgentShield gate API/UI.
  If no approval is needed, it finishes automatically with a final answer.
## Notes

- Destructive actions such as `rm -rf`, `git reset --hard`, and `DROP TABLE` are blocked by rules.
- High-risk actions (for example `git push`) are routed to human approval.
- If no LLM key is provided, unknown risky actions fall back to conservative rule/threshold behavior.

