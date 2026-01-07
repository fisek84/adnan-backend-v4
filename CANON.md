# CANON — Adnan.AI / Evolia OS (v2.2)

Adnan.AI is an AI Business Operating System.  
It is not a chatbot, assistant, or feature-driven AI.

---

## Fundamental Laws

Initiator ≠ Owner ≠ Executor. This separation is absolute.

READ and WRITE paths are strictly separated.

No execution is allowed without explicit governance approval.

No component may perform implicit actions or side effects.

Every action has a real cost: time, authority, or resources.

Intelligence may advise, propose, and translate intent, but never execute side effects.

Agents execute approved tasks but never self-authorize, escalate, or invent intent.

Workflows orchestrate state transitions and governance gates before execution.

UX reflects system truth and never invents state, intent, or approval.

If intent is unclear, the system must stop.

If approval is missing, the system must block.

No component may exceed the authority it can control.

No unbounded loops, autonomous escalation, or hidden persistence.

Every decision must be traceable and auditable (approval_id + execution_id + audit trail).

Stability is prioritized over apparent intelligence.

---

## Canonical Workflow Separation (SSOT)

### READ (Advisory) path
- Produces: `text` + `proposed_commands` (intent/proposals only)
- Must not: create side effects, write to Notion, or execute tasks

### WRITE (Execution) path
- Requires: explicit approval gate
- Executes: only after governance approval

---

## CEO Console Execution Flow (SSOT)

### Canon
- The LLM (CEO Advisor) is **READ-only** and advisory.
- The LLM may propose commands but **never performs side effects**.
- All side effects (e.g., Notion writes) must go through the approval-gated backend execution path.

### Flow (immutable)
1) `POST /api/chat` returns:
   - `text`
   - `trace` (including `trace.ops_plan` when present)
   - `proposed_commands` (proposals only; no execution)
2) User explicitly approves a proposal in UI:
   - UI sends `POST /api/execute/raw` with the approved proposal payload (SSOT)
   - Response must return `BLOCKED` + `approval_id` (+ execution tracking)
3) UI calls `POST /api/ai-ops/approval/approve` with `approval_id`
4) Deterministic executor performs the write:
   - Notion Ops Executor runs `NotionService.execute(ai_command)`
   - `notion_write` is a wrapper; the actual intent is `params.ai_command.intent`

### Frontend truth constraints (immutable)
- Frontend must not auto-execute proposals.
- Frontend must not reuse old proposals or template user text.
- The **approved proposal is the single source of truth** for the execution payload.
- Execution payload must be derived from the approved proposal object exactly.

---

## Proposed Commands Canon (when ops_plan exists)

### Rule
When `trace.ops_plan` exists, `proposed_commands` MUST contain `notion_write` proposals with `params.ai_command`.

- `ceo.command.propose` MUST NOT be added in this case.
- `ceo.command.propose` is allowed ONLY as fallback when ops_plan is missing or plan generation fails.

### Required proposed command envelope
Each proposed command MUST follow this envelope:

- `command`: `"notion_write"`
- `intent`: `"notion_write"`
- `dry_run`: `true`
- `requires_approval`: `true`
- `params`: `{ "ai_command": { ... } }`
- `risk`: `"LOW"`
- `scope`: `"api_execute_raw"`
- `payload_summary`: must include:
  - `endpoint`: `"/api/execute/raw"`
  - `canon`: `"CEO_CONSOLE_EXECUTION_FLOW"`
  - `source`: `"ceo_console"`

---

## Canonical Regression Guarantee (Happy Path)

The system MUST have a deterministic, executable Happy Path test.

The canonical Happy Path is: Initiator → BLOCKED → APPROVED → EXECUTED.

This path MUST be testable without UI, manually, or interpretation.

The canonical regression test is a CLI-based test (`test_happy_path.ps1`).

### Happy Path SSOT endpoints (immutable)
1) `POST /api/ceo/command` OR `POST /api/chat` → returns proposals (`proposed_commands`)
2) `POST /api/execute/raw` → returns `approval_id` + `execution_id` in BLOCKED state
3) `POST /api/ai-ops/approval/approve` → resumes execution and reaches EXECUTED/COMPLETED
4) `GET /api/ceo/console/snapshot` (optional verification) → reflects updated state

### PASS criteria (must all hold)
- `proposed_commands.length >= 1`
- `/api/execute/raw` returns a non-empty `approval_id` and `execution_id`
- Approve returns an execution result that is terminal: `COMPLETED` (or equivalent)
- If a write command was approved, the target system (e.g., Notion) reflects the change

### FAIL criteria (any one is fail)
- Missing proposals
- Missing approval_id/execution_id
- Approve blocked, rejected, or non-terminal
- 403 from policy gates (OPS_SAFE_MODE / token enforcement) during WRITE path

Any change to governance, orchestration, approval, or execution layers MUST pass the Happy Path test without modification.

If the Happy Path test fails, the change is invalid and MUST be reverted.

The Happy Path test is immutable and may not be adapted to fit new behavior.

The system behavior must adapt to the test, never the test to the system.

Absence of a passing Happy Path test means the system is non-operational.

---

## Design Constraint (Physics Rule)

The system must respect physical constraints (time, energy, information, authority)  
before attempting intelligence or autonomy.

Any violation of this canon invalidates the system design.
