# Fix: false-positive memory_write proposals + pending-proposal dismiss loop

## Root cause
- `memory_write`/"expand knowledge" intent detection in `services/ceo_advisor_agent.py` matched verbs anywhere in the message (e.g. `nauci` inside the normal phrase "u nauci"), which caused false-positive approval-gated `memory_write` proposals on normal Q&A.
- Pending proposal handling in `routers/chat_router.py` could clear pending state but then re-persist a new pending proposal in the *same* request after downstream routing, leading to replay loops where a later short "da" would still replay.

## Fix (invariant)
### Memory write allowlist gate (command-at-start)
Memory write intent can activate **only** when the user message (trimmed, case-insensitive) starts with one of these prefixes:
- `zapamti` / `zapamti ovo`
- `proširi znanje` / `prosiri znanje`
- `remember this`
- `learn this`
- `nauci` / `nauči` (**only** as an explicit command; requires `:`)

…and includes a valid payload:
- `"<command>: <payload>"` (colon required), OR
- `"<command> <payload>"` only for localized commands, only if payload length >= 15 and it does not look like a question (e.g. does not end with `?`).

Important: mid-sentence words like "u nauci" never trigger, because commands must match at the start of the message.

Implementation:
- Added `_parse_memory_write_allowlist_command()` and rewired `_is_memory_write_request()` / `_is_expand_knowledge_request()` to use it.
- Proposal payload now uses the parsed payload (not the full prompt) across deterministic/offline/fail-soft paths.

### Pending proposal dismiss (NO) hard-clear
- Extended pending-response classification to recognize the required DISMISS phrases (BHS+EN).
- Introduced a per-request `pending_declined` flag: once the user replies `NO` while pending, we clear pending state and **suppress re-persisting** any new pending proposals later in the same request.

## Tests
Added regression tests in `tests/test_memory_write_allowlist_and_pending_dismiss.py`:
1) Normal Q&A must not trigger memory_write proposal
2) Valid allowlisted memory commands must trigger proposal
3) Pending proposal exit: long dismiss phrase + `cancel` must clear pending; `da` still replays when pending

Pytest output:
```bash
C:/adnan-backend-v4/.venv/Scripts/python.exe -m pytest -q \
  tests/test_memory_write_allowlist_and_pending_dismiss.py \
  tests/test_ceo_real_delegation_to_rgo.py::test_pending_proposal_decline_clears_replay

......                                                                   [100%]
6 passed in 15.96s
```

## Risk
Low.
- Changes are narrowly scoped to deterministic intent gating and pending-proposal state handling.
- Governance is unchanged: memory writes remain approval-gated.

## Backward compatibility
- Removes legacy mid-sentence keyword triggers for memory writes (by design).
- Keeps existing explicit command workflows (`Zapamti...`, `Proširi znanje...`, `Remember this...`) and makes them safer/deterministic.
