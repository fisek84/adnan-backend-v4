# CEO Advisor SSOT-smart audit (Phase 0)

Date: 2026-02-21

## /api/chat request path (CEO Advisor)

- Snapshot hydration/injection happens in the chat router:
  - The incoming request provides `payload.snapshot`.
  - `routers/chat_router.py` injects the same snapshot into the grounding pack (`gp_for_agent["notion_snapshot"] = snap_for_agent`) and passes it to the CEO Advisor via `ctx_for_agent["notion_snapshot"]` and `ctx_for_agent["snapshot"]`.
  - `used_sources` (grounding trace) should include `notion_snapshot` when snapshot is present.

## Where tasks/goals are extracted (and why extracted_tasks_count can be 0)

- Extraction is done in `services/ceo_advisor_agent.py` via `_extract_goals_tasks_with_meta(snapshot_payload)`.
  - It prefers `dashboard.tasks/goals` when present, but explicitly prevents an empty dashboard list from overriding a non-empty `payload.tasks/goals`.
  - It also enforces an invariant: if `snapshot_tasks_count > 0` but extraction yields `0`, it forces fallback to an available non-empty list.

- The contradiction case observed in prod traces (`snapshot_tasks_count > 0` but narrative says “nema taskova”) can still happen if:
  - the final natural-language response is produced by an LLM path that ignores/contradicts snapshot context, OR
  - an upstream path provides a snapshot wrapper/count but the list used by the narrative path is empty.

Mitigation added in this work:
- Post-answer validator in `routers/chat_router.py` overrides “no tasks/goals” denials when snapshot counts are non-zero.
- Narrative fallback in `services/ceo_advisor_agent.py`: if `tasks` ends up empty but `snapshot_payload["tasks"]` is non-empty, fall back to snapshot tasks for the narrative path.

## Where “TASKS (top 5)” is generated and why it is fixed at 5

- The standard dashboard table is produced by `services/ceo_advisor_agent.py::_render_snapshot_summary(goals, tasks)`.
- It prints `TASKS (top 5)` and enumerates up to 5 items by design (hard-coded UI-friendly cap).

## Task-intent coverage gaps (before this work)

Existing deterministic handling:
- Explicit show/list phrases (e.g. “pokaži zadatke”, “navedi taskove”) are handled deterministically.

Previously missing deterministic handling (now covered by the SSOT Task Query Engine):
- “svi taskovi / prikaži sve / listaj sve” (must return ALL tasks, not top 5)
- “taskovi za danas” (due == today)
- “overdue / kasne / zakasnili” (due < today and not completed)
- “po statusu: <X>” (filter by status, incl. Not Started → to do)
- “po prioritetu: <X>” (filter by priority)

