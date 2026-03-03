# AgentShield Testbench: Setup and Run

This document provides a reproducible process to test the AgentShield project.

## 1) Prerequisites

- Python `3.10+`
- `pip`
- Terminal access (PowerShell, cmd, or bash)

No API keys are required for this smoke test.

## 2) Open the project root

Use the repository folder that contains `backend/`, `frontend/`, and `testbench/`.

Example:

```powershell
cd "..\agentshield"
```

## 3) Create and activate virtual environment

### PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Bash

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 4) Install dependencies

```powershell
pip install -r requirements.txt
```

## 5) Start AgentShield API (Terminal A)

```powershell
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

Keep this terminal running.

## 6) Run automated smoke test (Terminal B)

Open a second terminal in the same project root, activate `.venv`, then run:

```powershell
python testbench/smoke_test.py --base-url http://127.0.0.1:8000 --repo-path .
```

What this verifies:

1. `GET /health` is reachable.
2. Safe file-read action is evaluated as executable.
3. Destructive shell action (`rm -rf`) is blocked.
4. Human-gated action (`git push`) becomes pending.
5. Pending gate can be rejected through decision API.

Expected ending line:

```text
All smoke tests passed.
```

## 7) Optional manual API checks with provided payload files

With API still running:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/evaluate-action" -H "Content-Type: application/json" --data-binary "@testbench/payloads/evaluate_safe.json"
curl.exe -X POST "http://127.0.0.1:8000/api/v1/evaluate-action" -H "Content-Type: application/json" --data-binary "@testbench/payloads/evaluate_blocked.json"
curl.exe -X POST "http://127.0.0.1:8000/api/v1/gates/propose" -H "Content-Type: application/json" --data-binary "@testbench/payloads/propose_human_gate.json"
```

## 8) Optional UI check

Open:

- `http://127.0.0.1:8000/`

Use the built-in page to submit actions and observe gate/event behavior.

## 9) Stop services

- In Terminal A, press `Ctrl+C` to stop `uvicorn`.
- Deactivate env when done:

```powershell
deactivate
```

