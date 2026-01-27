# Pending proposal behavior matrix (READ-only /api/chat)

This document describes how `/api/chat` behaves when there is a **pending proposal** (stored per `session_id`) and the user sends a new message.

Key implementation:
- Classifier: [routers/chat_router.py](../routers/chat_router.py#L477)
- Pending replay/cancel block: [routers/chat_router.py](../routers/chat_router.py#L1118-L1230)

## Behavior matrix

> **Zero-break for YES replay:** the **YES** path preserves the existing behavior (replays the last pending proposal unchanged) and returns `trace.intent = "approve_last_proposal_replay"`.

| Class | What it means (when pending exists) | Expected behavior | Trace intent |
|---|---|---|---|
| **YES** | User confirms they want to proceed/review the pending proposal | Replay the pending proposal; do not route as a new request | `approve_last_proposal_replay` |
| **NO** | User declines the pending proposal | Cancel/clear the pending proposal; continue normal routing on this turn | (normal routing) |
| **NEW_REQUEST** | User is changing direction / provides a new request while a pending proposal exists | Cancel/clear the pending proposal; continue routing with the new request (no replay) | (normal routing) |
| **UNKNOWN** | Not clearly a yes/no/new-request | Ask **once** to confirm (keep pending). If the user responds UNKNOWN again, auto-cancel and continue routing | `pending_proposal_confirm_needed` (first unknown only) |

## Examples (3–5 per class)

The classifier is heuristic and language-tolerant (BHS + English).

### YES
- "Da"
- "OK"
- "Slažem se"
- "Uradi to"
- "Yes"

### NO
- "Ne"
- "Nemoj"
- "Otkaži"
- "Stop"
- "No thanks"

### NEW_REQUEST (especially important)
- "Umjesto delegacije, napravi plan i prioritete."
- "Ne — želim samo plan (bez deliverable-a)."
- "Preskoči to; daj mi strategiju za outreach."
- "Instead, build a 7-day plan with priorities."
- "Bez delegacije: napravi checklistu i timeline."

### UNKNOWN
- "hmm"
- "?"
- "Ne znam"
- "Šta?"
- "..." (empty/whitespace)

## Test coverage

- **ACK discipline before delegation prompt** (unrelated to classifier, but part of the hardening contract):
  - [tests/test_ceo_real_delegation_to_rgo.py](../tests/test_ceo_real_delegation_to_rgo.py#L120-L122)

- **NEW_REQUEST cancels pending and routes**:
  - [tests/test_ceo_real_delegation_to_rgo.py](../tests/test_ceo_real_delegation_to_rgo.py#L370-L414)

- **UNKNOWN twice prompts once then auto-cancels**:
  - [tests/test_ceo_real_delegation_to_rgo.py](../tests/test_ceo_real_delegation_to_rgo.py#L430-L501)

- **SSOT missing ⇒ no fabricated goal/task tables** (adjacent safety requirement):
  - [tests/test_ceo_real_delegation_to_rgo.py](../tests/test_ceo_real_delegation_to_rgo.py#L503-L556)

- **Decline deliverables + new request does not re-enter confirmation jail**:
  - [tests/test_ceo_real_delegation_to_rgo.py](../tests/test_ceo_real_delegation_to_rgo.py#L559-L620)
