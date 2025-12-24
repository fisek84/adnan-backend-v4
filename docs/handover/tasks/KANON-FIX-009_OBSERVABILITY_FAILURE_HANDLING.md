# KANON-FIX-009 — Observability & Failure Handling (Phase 9)

## Status
DONE — 2025-12-24

## Scope
Implementiran observability + ops read-only dashboards + failure handling sloj, bez side-efekata u UI rutama. Sve rute su stabilizovane pod `/api/*` i verifikovane preko OpenAPI.

## Deliverables
### API (READ-ONLY / Ops)
- /api/metrics/
- /api/alerting/
- /api/audit/execution
- /api/audit/kpis
- /api/audit/export
- /api/ai-ops/agents/health
- /api/ai-ops/approval/pending
- /api/ai-ops/approval/approve
- /api/ai-ops/approval/reject
- /api/ai-ops/cron/status
- /api/ai-ops/cron/run
- /api/ai-ops/metrics/persist
- /api/ai-ops/alerts/forward
- /api/ceo/console/snapshot
- /api/ceo/console/weekly-memory

### Core behavior
- Approval lifecycle stabilizovan (approval vezan za execution_id; global backing store da izbjegne “Approval not found” između instanci).
- Execution governance KPI agregacija dostupna kroz audit sloj.
- Metrics/Alerting snapshot dostupni kao read-only ops konzole.
- Gateway routes usklađene (root vs /api) i potvrđene kroz openapi.json.

## Gates (Must pass)
- `.\test_runner.ps1` → ALL HAPPY PATH TESTS PASSED
- `python -m pre_commit run --all-files` → PASSED
- `python -m pytest -q` → PASSED

## Notes
- Root rute (`/metrics`, `/alerting`, `/ai-ops`, `/audit`) nisu canonical entrypoint; canonical je `/api/*`.
- CEO console snapshot postoji i na `/ceo/console/snapshot` (legacy), ali `/api/ceo/console/snapshot` je kanonski.
