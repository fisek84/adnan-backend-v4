CANON — Adnan.AI / Evolia OS (v2)

Adnan.AI is an AI Business Operating System.
It is not a chatbot, assistant, or feature-driven AI.

Fundamental Laws

Initiator ≠ Owner ≠ Executor. This separation is absolute.

READ and WRITE paths are strictly separated.

No execution is allowed without explicit governance approval.

No component may perform implicit actions or side effects.

Every action has a real cost: time, authority, or resources.

Intelligence may advise, but never execute.

Agents execute tasks but never decide or interpret intent.

Workflows orchestrate state transitions, not execution.

UX reflects system truth and never invents state or intent.

If intent is unclear, the system must stop.

If approval is missing, the system must block.

No component may exceed the authority it can control.

No unbounded loops, autonomous escalation, or hidden persistence.

Every decision must be traceable and auditable.

Stability is prioritized over apparent intelligence.

Canonical Regression Guarantee (Happy Path)

The system MUST have a deterministic, executable Happy Path test.

The canonical Happy Path is: Initiator → BLOCKED → APPROVED → EXECUTED.

This path MUST be testable without UI, manually, or interpretation.

The canonical regression test is a CLI-based test (test_happy_path.ps1).

Any change to governance, orchestration, approval, or execution layers
MUST pass the Happy Path test without modification.

If the Happy Path test fails, the change is invalid and MUST be reverted.

The Happy Path test is immutable and may not be adapted to fit new behavior.

The system behavior must adapt to the test, never the test to the system.

Absence of a passing Happy Path test means the system is non-operational.

Design Constraint (Physics Rule)

The system must respect physical constraints
(time, energy, information, authority)
before attempting intelligence or autonomy.

Any violation of this canon invalidates the system design.