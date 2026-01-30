# Audit: `assistant_identity` intent misclassification via pasted headings

## Summary
A production bug occurs when users ask for plan/content analysis but the pasted content contains headings like `KO SI TI`, which (pre-fix) can trigger the CEO Advisor identity matcher. This sets `trace.intent = "assistant_identity"` and returns the CEO identity/intro template instead of analyzing the content.

## Where `assistant_identity` is detected / set
- Identity matcher (pre-fix): `services/ceo_advisor_agent.py::_is_assistant_role_or_capabilities_question`
  - It previously used `re.search(...)` over the *entire* user message string (i.e., it scanned the whole prompt including pasted payload), so `ko si` appearing anywhere could return True.
- Identity deterministic early-return: `services/ceo_advisor_agent.py` (LLM gate section)
  - If `_is_assistant_role_or_capabilities_question(base_text)` is True, the agent returns `_assistant_identity_text(...)` and sets:
    - `trace.intent = "assistant_identity"`
    - `exit_reason = "deterministic.assistant_identity"`

Concrete locations (current repo snapshot):
- Identity matcher: `services/ceo_advisor_agent.py` around line 1300.
- Identity response text template: `services/ceo_advisor_agent.py` around line 1031.
- Where `trace.intent` is set to `assistant_identity`: `services/ceo_advisor_agent.py` around lines 3948–3949.

## Proof that the matcher considered the full message
- The input passed into `_is_assistant_role_or_capabilities_question(...)` is `base_text` (the full user message) in the deterministic allowlist block.
- Because the prior implementation used `re.search` with word-boundaries (not anchored), any occurrence of `ko si` inside the message (including headings like `KO SI TI (POZICIJA)` inside pasted documents) could match.

## Hotfix (minimal)
- Tightened `_is_assistant_role_or_capabilities_question` to only match when the *entire message* is a short, single-line, explicit identity/capability question anchored to start/end.
- This prevents headings inside pasted documents from hijacking intent while keeping explicit identity prompts working.

## Non-goals / untouched areas
- Did not change gateway leak-guard sanitize/bypass logic.
- Did not broaden prompt allowlists.
- Did not change overall routing design.
