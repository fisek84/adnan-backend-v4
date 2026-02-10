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
