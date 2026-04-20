# Pending proposal behavior matrix (READ-only /api/chat)

This document describes how `/api/chat` behaves when there is a **pending proposal** (stored per `session_id`) and the user sends a new message.

This contract is **Block 1**: Turn Interpretation Authority Gate is the authority for how a pending proposal interacts with the current message.

Key implementation:
- Turn gate (deterministic): [services/turn_interpretation_authority_gate.py](../services/turn_interpretation_authority_gate.py)
- Gate integration + pending replay/dismiss/clarify: [routers/chat_router.py](../routers/chat_router.py#L2440-L2665)

## Block 1 behavior matrix (gate-driven)

### Principles

- Pending proposal is **background** unless the user sends an explicit, allowlisted **confirm** or **dismiss**.
- **Current-turn primacy:** when the current message is a normal question (or an anchored meta question), the request is handled as a new turn; pending must not “hijack” routing.
- **Ambiguous turns** do **not** enter a legacy confirm-needed / unknown loop. They return a **clarify** response.

### Categories when pending exists

| Gate category | What it means (when pending exists) | Expected behavior | Trace intent |
|---|---|---|---|
| **PENDING_PROPOSAL_CONFIRM** | User explicitly confirms/replays pending proposal (strict allowlist) | Replay the pending proposal | `approve_last_proposal_replay` |
| **PENDING_PROPOSAL_DISMISS** | User explicitly dismisses/cancels pending proposal (strict allowlist) | Clear pending proposal; continue normal routing on this turn | (normal routing) |
| **AMBIGUOUS** | Turn is empty/too short/unclear (and not allowlisted) | Ask for clarification; keep pending visible (no replay, no confirm-needed loop) | `clarify` |
| **NORMAL_QUESTION** | A normal request/question while pending exists | Handle as a normal new turn (current-turn primacy) | (normal routing) |
| **META_ASSISTANT** | Meta question with an explicit anchor (e.g., memory/identity/governance) | Handle as meta; current-turn primacy | (meta routing) |
| **CONTROL_TURN** | Control commands (e.g., Notion Ops toggle) | Execute control routing (independent of pending proposal) | (control routing) |

## Examples (non-exhaustive)

These examples are intentionally minimal. The contract is enforced via the gate’s strict allowlists and deterministic ambiguity handling.

### PENDING_PROPOSAL_CONFIRM
- "Da"
- "Ponovi prijedlog"
- "Odobri"

### PENDING_PROPOSAL_DISMISS
- "Ne"
- "Otkaži"
- "Stop"

### AMBIGUOUS
- "hmm"
- "?"
- "..." (empty/whitespace)

### NORMAL_QUESTION
- "Umjesto toga, napravi plan i prioritete."
- "Objasni mi CAP theorem ukratko."

## Replay invariants (important)

When the pending proposal is replayed, the **canonical action must be the same**, but the replay is not required to be **byte-identical** in every human-facing text field.

Examples of acceptable variance (non-normative):
- A human-facing `reason` string can be shortened/normalized (while `command` and the canonical `args` fields remain the same).

## Superseded (pre-Block 1) — obsolete behavior

The legacy classifier documented an **UNKNOWN** state that would:
- prompt once with `pending_proposal_confirm_needed`, then
- auto-cancel pending on the next UNKNOWN.

This UNKNOWN confirm-needed loop is **superseded** by Block 1 gate behavior. Ambiguous turns now return **clarify** and do not implement the legacy prompt/auto-cancel loop.

## Test coverage

- Gate regression matrix (pins the 5-field decision contract):
  - [tests/test_turn_interpretation_authority_gate_matrix.py](../tests/test_turn_interpretation_authority_gate_matrix.py)

- Pending + ambiguous → clarify; explicit confirm → replay:
  - [tests/test_ceo_real_delegation_to_rgo.py](../tests/test_ceo_real_delegation_to_rgo.py#L480-L660)

- Minimal trace includes `canon` + `turn_gate` keys:
  - [tests/test_chat_debug_gating.py](../tests/test_chat_debug_gating.py)
