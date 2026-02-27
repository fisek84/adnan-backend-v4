## Fix: stop false "memory capability" boilerplate for human-memory questions

### Problem
Some user questions containing `memorija/memory` (in the *human cognition* sense) were incorrectly routed into the assistant/system memory capability disclosure path, producing governance boilerplate.

### Root cause
- `services/ceo_advisor_agent.py::_is_memory_capability_question()` previously triggered on a bare `memorij*|memory` match.
- In offline/CI mode (`use_llm=True` but LLM not configured), the LLM-gate fallback could also surface the `memory_model_001` KB content as generic KB snippets, which reintroduced the same governance disclosure for human-memory questions.

### Invariant (required behavior)
- **Memory write governance unchanged**: writes remain approval-gated via strict allowlist parsing (`memory_write.v1`).
- **Allowlist priority**: explicit memory-write commands must not be shadowed by capability/meta routing.
- **Capability disclosures only when clearly about assistant/system memory** (second-person / identity markers / explicit "do you remember"-style phrasing).
- **Human-memory questions stay normal Q&A** (no governance boilerplate).

### What changed
1) `services/ceo_advisor_agent.py`
- Updated `_is_memory_capability_question()` to require positive assistant/system signals (not just the keyword), while preserving strict memory-write allowlist priority.
- In the offline LLM-gate fallback:
  - Handle `memory_capability` and `memory_write` *before* returning KB-snippet fallback (preserves governance invariants).
  - Filter out `memory_model_001` from KB-snippet fallback to avoid leaking assistant-memory governance into human-memory queries.
  - Avoid returning an empty KB-snippet response if all hits were filtered.

2) `tests/test_memory_capability_gating.py`
- Added regression coverage:
  - Human-memory prompt does **not** trigger `memory_capability` or governance boilerplate.
  - Assistant-memory meta question routes to `assistant_memory` and includes `kratkoro/dugoro` explanation.
  - "Zapamti ovo: ..." still yields an approval-gated `memory_write` proposal.

### Validation
- Full suite: `python -m pytest -q` -> **521 passed, 4 skipped**

### Risk
Low. Changes are localized to deterministic intent gating and offline fallback ordering/filtering; memory-write governance remains approval-gated and is explicitly prioritized.