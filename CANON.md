# CANON — Adnan.AI / Evolia OS (v2.1)

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
