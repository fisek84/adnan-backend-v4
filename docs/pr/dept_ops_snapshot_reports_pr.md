# Dept Ops: Snapshot-driven Daily Brief + KPI Preview

## Why
Dept Ops izvještaji su bili "prazni" jer su koristili samo snapshot meta. Cilj je da `read_only.query` ops modovi (daily brief / KPI weekly preview / snapshot health) koriste postojeći Notion knowledge snapshot payload (`payload.databases[*].items`) bez novih tool IDs ili novih integracija.

## What changed
- Snapshot export (existing refresh/sync path): svaki item i dalje sadrži `id/notion_id/title/url/created_time/last_edited_time`, i dodatno `fields` (allowlisted + normalizovan tip) i `truncated` flag.
- SSOT allowlist: centralni mapping `SNAPSHOT_FIELDS_ALLOWLIST` po `db_key`.
- `read_only.query` ops modes:
  - `ops.daily_brief`: brojevi + top urgent list iz snapshot fields.
  - `ops.kpi_weekly_summary_preview`: trendovi (up/down/flat) iz numeričkih KPI fieldova; ako nema numeričkih fieldova → `missing_reason`.
  - `ops.snapshot_health`: prisutni db_keys + count + errors.
- Dept Ops output: tačno 4 sekcije (Summary/Evidence/Recommendation/Proposed Actions) i Summary uključuje snapshot-driven brojeve.

## Hard constraints honored
- No new tool IDs; Dept Ops allowlist ostaje `read_only.query`.
- No Notion writes without approval; proposals remain `dry_run=true` + `requires_approval=true`.
- Snapshot fields export is capped + deterministic; no full Notion dump.

## KPI limitation (explicit)
KPI radi samo ako KPI rows imaju numeric fields (number/formula/rollup koji resolve u number). U suprotnom `ops.kpi_weekly_summary_preview` vraća `missing_reason=no_numeric_kpi_fields_in_snapshot`.

## Tests
- `pytest -q` passes.
- Added SSOT allowlist test + expanded ops mode tests with seeded snapshot payload including fields + caps assertions.

## Proof pointers (file:line)

Snapshot export (`fields` + caps + row fallback)
- `services/notion_service.py:1503` Snapshot item fields extraction (SSOT allowlist + capped)
- `services/notion_service.py:1707` `_extract_allowlisted_fields()` (per-row safe; never raises)
- `services/notion_service.py:2033` Snapshot item includes `fields` + `truncated`

SSOT allowlist
- `services/snapshot_fields_allowlist.py:31` `SNAPSHOT_FIELDS_ALLOWLIST`
- `services/snapshot_fields_allowlist.py:98` `allowlist_for_db_key()` + unknown default behavior

Read-only ops modes (snapshot-driven)
- `services/tool_runtime_executor.py:174` `_ops_daily_brief_from_snapshot()`
- `services/tool_runtime_executor.py:308` `_ops_kpi_weekly_preview_from_snapshot()`
- `services/tool_runtime_executor.py:443` KPI `missing_reason=no_kpi_rows_in_snapshot`
- `services/tool_runtime_executor.py:445` KPI `missing_reason=no_numeric_kpi_fields_in_snapshot`
- `services/tool_runtime_executor.py:450` `_ops_snapshot_health_from_snapshot()`

Dept Ops wrapper (exact 4 sections + embedded read-only ops calls)
- `services/department_agents.py:147` `_format_dept_text()` enforces 4 sections in order
- `services/department_agents.py:326` Dept Ops invokes `read_only.query` for `ops.daily_brief`
- `services/department_agents.py:363` Dept Ops invokes `read_only.query` for KPI preview (keyword-gated)

Tests
- `tests/test_read_only_query_ops_modes.py:33` Seeds snapshot payload (daily brief)
- `tests/test_read_only_query_ops_modes.py:151` Seeds snapshot payload (KPI preview)
- `tests/test_snapshot_fields_allowlist_ssot.py:11` SSOT allowlist coverage
