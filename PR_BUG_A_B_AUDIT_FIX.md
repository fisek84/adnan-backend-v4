# PR: Audit + minimal fixes for Bug A and Bug B (no contract changes)

Date: 2026-01-26

## Constraints (confirmed)
- No refactor
- No API contract changes
- No new agents / heuristics / recall short-circuits
- Additive + minimal only
- Test-first proofs included (regression/unit/integration)

---

## A) BUG — Deliverable re-trigger (sticking + re-delegating)

### Root cause
Deliverable delegation was inferred from the last deliverable-intent found in `ConversationStateStore` summary text. After a successful deliverable execution, there was no persisted “consumed/completed” marker for that specific deliverable, so subsequent generic confirmations could re-trigger the same delegation.

### Audit (exact locations)
- Where “pending_deliverable” comes from (it is **not** stored as a dedicated field; it is derived by parsing the conversation summary):
  - Conversation summary persistence: [services/ceo_conversation_state_store.py](services/ceo_conversation_state_store.py#L88-L176) (`append_turn` stores bounded turns)
  - Summary generation format (`N) USER:` lines): [services/ceo_conversation_state_store.py](services/ceo_conversation_state_store.py#L60-L86)
  - Deliverable extraction from summary: [services/ceo_advisor_agent.py](services/ceo_advisor_agent.py#L1895-L1933)
- Where deliverable confirmation/continue is detected:
  - Confirm keywords (explicit only): [services/ceo_advisor_agent.py](services/ceo_advisor_agent.py#L1881-L1894)
  - Continue keywords (explicit only): [services/ceo_advisor_agent.py](services/ceo_advisor_agent.py#L1811-L1822)
- Where completion is now marked + checked:
  - Persist completion marker (meta): [services/ceo_advisor_agent.py](services/ceo_advisor_agent.py#L1843-L1859)
  - Check completed marker (meta): [services/ceo_advisor_agent.py](services/ceo_advisor_agent.py#L1860-L1872)
  - Guard to prevent re-delegation after completion unless explicit continue: [services/ceo_advisor_agent.py](services/ceo_advisor_agent.py#L2246-L2266)

### Minimal fix
Add an additive meta marker keyed by a deterministic deliverable hash (`deliverable_last_completed_hash`) and consult it before allowing a follow-up confirmation to re-trigger the same deliverable.

### Proof (test)
- Regression test: [tests/test_ceo_deliverable_resets_after_execution.py](tests/test_ceo_deliverable_resets_after_execution.py)
  - Scenario: request → confirm (executes once) → new prompt (“ok”/ack) → assert no new delegation.

### Manual validation (CEO Console)
1) Send a deliverable drafting request (e.g. follow-up email).
2) Confirm with explicit phrase (`"uradi to"` / `"slažem se"`).
3) Send a generic acknowledgement (`"ok"`, `"slažem se"` without `"uradi to"`, or a new task).
4) Expected: no second Revenue/Growth delegation unless you explicitly say `"nastavi" / "još" / "proširi" / "iteriraj"`.

---

## B) BUG — “Memorija je prazna / nema kontinuitet” (SSOT)

### Root cause
Memory SSOT is file-backed JSON; when storage/provider is unavailable/corrupted, snapshot export must fail-soft to `{}` so routers/agents can deterministically mark memory as missing via trace. Additionally, the only acceptable proof of continuity is the approval→executor→write→snapshot path (no recall shortcuts).

### Audit (exact locations)
- SSOT type/path/env:
  - File-backed SSOT (JSON) with `MEMORY_PATH` env var (default `adnan_ai/memory/memory.json`): [services/memory_service.py](services/memory_service.py#L20-L67)
  - Test harness isolates memory path: [tests/conftest.py](tests/conftest.py#L55-L73)
- Write path (approval-gated):
  - Post-approval dispatch: [services/execution_orchestrator.py](services/execution_orchestrator.py#L343-L371)
  - Executor entrypoint: [services/memory_ops_executor.py](services/memory_ops_executor.py#L28-L115)
  - Canonical sink (upsert) into `memory["memory_items"]` + persist: [services/memory_service.py](services/memory_service.py#L82-L175)
- Read path:
  - Read-only export used by routers: [services/memory_read_only.py](services/memory_read_only.py#L33-L79)

### Real scenario where approve exists but executor doesn’t write
- If a command is approved but its metadata is missing `metadata.identity_id`, `MemoryOpsExecutor.execute` raises (hard requirement): [services/memory_ops_executor.py](services/memory_ops_executor.py#L39-L46)
- If the command isn’t classified as `memory_write` (wrong `intent/command`), orchestrator won’t dispatch to `MemoryOpsExecutor`.

### Minimal fix
- Make `ReadOnlyMemoryService.export_public_snapshot()` fail-soft and return `{}` on provider errors or corrupted shapes (no exceptions).
- Add DEBUG-only trace fields in routers (no response-shape changes) so we can prove which provider was used and whether memory export failed.

### Proof (tests)
Unit tests (fail-soft export):
- [tests/test_memory_read_only_fail_soft.py](tests/test_memory_read_only_fail_soft.py)

Trace proofs (missing_inputs contains `"memory"` when export fails):
- `/api/chat`: [tests/test_api_chat_memory_missing_trace.py](tests/test_api_chat_memory_missing_trace.py)
- `/api/ceo/command` wrapper: [tests/test_ceo_command_trace_memory_missing.py](tests/test_ceo_command_trace_memory_missing.py)

Integration proof (approval → execute → write → snapshot reflects write):
- [tests/test_memory_write_e2e.py](tests/test_memory_write_e2e.py)
- [tests/test_memory_recall_continuity.py](tests/test_memory_recall_continuity.py) (name kept, but asserts snapshot continuity; no recall heuristics)

Debug trace fields proof (CEO console route):
- [tests/test_ceo_console_debug_memory_trace.py](tests/test_ceo_console_debug_memory_trace.py)

### Manual validation (CEO Console)
1) Trigger a memory write proposal, approve it, and execute.
2) Next `/api/chat` should show `trace.used_sources` includes `"memory"` and `memory_items_count` > 0 (when debug enabled).
3) If storage is misconfigured/unavailable, you should see `trace.missing_inputs` contains `"memory"` and `trace.memory_error` populated (debug-only).

---

## Quick local commands
- `pytest -q tests/test_ceo_deliverable_resets_after_execution.py`
- `pytest -q tests/test_memory_read_only_fail_soft.py tests/test_memory_write_e2e.py`
- `pytest -q tests/test_api_chat_memory_missing_trace.py tests/test_ceo_command_trace_memory_missing.py`
