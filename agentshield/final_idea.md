# AgentShield — Principled Oversight for Autonomous AI Coding Agents

## One-Liner

> A real-time supervisory middleware that makes AI coding agents safe to deploy by scoring every action for reversibility, estimating blast radius, detecting intent drift, running adversarial review, and enabling one-click rollback — intervening *only* when it matters.

---

## The Problem

AI coding agents (Devin, Codex, Cursor Agent) are powerful enough to execute real actions — file writes, shell commands, database mutations, deployments. But their oversight models are broken:

- **Too autonomous** → agents execute freely, occasionally causing catastrophic damage
- **Too interruptive** → constant "approve?" dialogs that humans stop reading (oversight theater)

**Nobody has solved risk-proportional oversight** — intervene precisely when stakes are high, and only then.

---

## What AgentShield Is

A **middleware layer** that sits between any AI agent and execution. You don't replace the agent — you wrap it.

```
Human gives goal → AI Agent proposes action → AgentShield evaluates → Decision
                                                  ↓
                                          Low risk → auto-execute
                                          High risk → pause + explain + ask human
                                          Drifted → alert + abort
                                          If mistake → one-click rollback
```

---

## The Five Pillars

### 1. ⚖️ Reversibility Classification
Every agent action is scored on a reversibility scale **before** execution.

| Action | Score | Gate |
|---|---|---|
| Read a file | 1.0 (fully reversible) | Auto-execute |
| Write to a new file | 0.8 | Auto-execute |
| Modify existing file | 0.5 | Log + execute |
| Run `DROP TABLE` | 0.0 (irreversible) | **Block — require human** |
| Run unknown shell command | ? | **LLM-classify, then decide** |

**Implementation:**
- Rule-based classifier for ~30 common operations (file CRUD, git, SQL, shell)
- GPT-4o fallback for ambiguous commands (one API call with structured output)
- Decision threshold is configurable per session

---

### 2. 💥 Blast Radius Estimation
Before a code change executes, estimate **how much of the codebase it affects**.

> *"This change modifies `utils/auth.py`, which is imported by 14 files across 3 modules. It also touches the `users` table, which has 2 foreign key dependencies."*

**Implementation:**
- Python `ast` module to parse imports and build a basic dependency graph
- Regex-based detection of SQL table references in the proposed change
- Output: a plain-English summary + a count of affected files/tables/APIs
- Pre-compute the dependency graph once at session start (fast for repos < 10k files)

---

### 3. 🧭 Intent Drift Detection
Capture the human's original goal as a semantic embedding. After each agent action, compare the current trajectory against the original intent.

> *Original goal: "Optimize slow database queries"*
> *Agent is now doing: "Restructuring the users table schema"*
> *Drift score: 0.38 (⚠️ significant drift detected)*

**Implementation:**
- `text-embedding-3-small` to embed the original goal
- After each action, embed a summary of what the agent just did
- Cosine similarity between goal embedding and running action window
- Alert threshold: similarity < 0.5 → warn; < 0.3 → block

---

### 4. 🧑‍⚖️ Adversarial Review (Devil's Advocate Agent)
For any action scored as medium-to-high risk, a **second, independent LLM call** reviews the proposed action and specifically tries to find problems.

> *Primary agent: "Adding an index on `orders.user_id`"*
> *Devil's advocate: "This table has a large row count based on the schema. Index creation may lock the table. Consider `CREATE INDEX CONCURRENTLY` instead."*

**Implementation:**
- One additional GPT-4o call per flagged action
- System prompt: "You are a senior engineer reviewing an AI agent's proposed action. Find risks, edge cases, and potential failures. Be specific."
- Input: the proposed action + relevant file context + blast radius output
- Output: structured risk assessment (risks found: yes/no, details, suggested alternative)
- **Cost:** ~$0.01-0.03 per review call — trivial with OpenAI credits

---

### 5. ⏪ Action Timeline & One-Click Rollback
Every action the agent takes is logged as a checkpoint in a **visual timeline**. If something goes wrong, the human can roll back to any previous checkpoint.

**Implementation:**
- Each action is a node: `{id, timestamp, action_type, description, risk_score, files_changed, reversible}`
- File changes: store diffs (use `difflib` in Python)
- Shell commands: log the command + output + inverse command (where applicable)
- Rollback = apply stored diffs in reverse order up to the selected checkpoint
- UI: a horizontal timeline scrubber with color-coded risk indicators

---

## What the UI Looks Like

A **real-time operator control panel** — not a chatbot, not a dashboard of graphs.

```
┌─────────────────────────────────────────────────────────┐
│  AgentShield Control Panel                              │
├──────────────────────┬──────────────────────────────────┤
│                      │                                  │
│  SESSION GOAL        │  CURRENT ACTION                  │
│  "Optimize slow      │  Agent wants to run:             │
│   DB queries"        │  ALTER TABLE users ADD INDEX...   │
│                      │                                  │
│  INTENT ALIGNMENT    │  ⚖️ Reversibility: 0.3 (LOW)     │
│  ████████░░ 0.72     │  💥 Blast Radius: 3 files,       │
│                      │     1 table, 0 APIs              │
│  DRIFT TREND         │  🧑‍⚖️ Devil's Advocate:            │
│  ▁▂▂▃▅ (rising)      │  "Table lock risk on large       │
│                      │   dataset. Consider CONCURRENTLY" │
│                      │                                  │
│                      │  [ ✅ Approve ] [ ✏️ Modify ]     │
│                      │  [ 🛑 Abort  ] [ ⏪ Rollback ]   │
├──────────────────────┴──────────────────────────────────┤
│  ACTION TIMELINE                                        │
│  ●──●──●──●──◐──○  (5 of 6 actions executed)           │
│  ✅  ✅  ✅  ✅  ⏳  ○                                    │
│  Read Query Analyze Rewrite ADD    (pending)            │
│  file  logs  AST   query  INDEX                         │
└─────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Backend | **Python + FastAPI** | Fastest for agent orchestration + async |
| Agent loop | **OpenAI Assistants API** (function calling) | Direct OpenAI integration, uses your credits |
| Reversibility | Rule-based + **GPT-4o** structured output | Handles known + ambiguous cases |
| Static analysis | **Python `ast`** + regex | Lightweight, no dependencies |
| Intent tracking | **text-embedding-3-small** + cosine similarity | Cheap, fast, effective |
| Adversarial review | **GPT-4o** (one call per flagged action) | Simple prompt engineering |
| Rollback engine | **Python `difflib`** + action log | No external dependencies |
| Frontend | **React** (Vite) | Fast to scaffold, easy timeline UI |
| Demo repo | **Purpose-built Python e-commerce app** | Triggers all 5 pillars cleanly |

---

## Demo Script (3 minutes)

1. **Setup** (30s): Show the demo repo — a Python e-commerce app with a database. Give the agent the goal: *"Optimize the slow database queries."*

2. **Safe actions auto-execute** (30s): Agent reads files, analyzes query logs, rewrites a SELECT query. All low-risk → AgentShield auto-approves. Timeline fills with green checkpoints. *"See — no interruptions for safe actions."*

3. **Blast radius warning** (30s): Agent proposes modifying `utils/db.py`. AgentShield shows: *"This file is imported by 14 files. 3 database tables referenced."* Human reviews and approves with context.

4. **The catch** (60s): Agent proposes `ALTER TABLE` + schema restructure. Three pillars fire simultaneously:
   - ⚖️ Reversibility: 0.1 (near-irreversible)
   - 🧭 Intent drift: 0.35 (far from "optimize queries")
   - 🧑‍⚖️ Devil's advocate: *"Schema change will break foreign key in orders table"*
   
   Human sees the full picture and aborts.

5. **Rollback demo** (30s): Show that if the action *had* executed, one click on the timeline rolls back to the last safe state.

6. **Closing** (30s): *"The agent wasn't malicious — it was trying to help. AgentShield is what makes the difference between a near-miss and a production outage."*

---

## Why This Wins

| Other Teams | AgentShield |
|---|---|
| "We built an AI agent with a confirm button" | We built the **trust infrastructure** that any agent needs |
| Binary approve/reject | **Risk-proportional** — 5 dimensions of evaluation |
| No memory of what happened | **Full action timeline + rollback** |
| Single-model trust | **Adversarial multi-model review** |
| No awareness of codebase impact | **Static analysis blast radius** |
| No goal tracking | **Semantic intent drift detection** |

**The pitch**: *"We're not building a better AI agent. We're building the missing layer that makes ALL AI agents safe enough to trust in production."*
