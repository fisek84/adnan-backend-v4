# Outcome Feedback Loop (OFL) — Runbook

## Smoke: Revenue & Growth Operator (read-only)

Napomena (COO readiness gate): Endpoint `/api/adnan-ai/input` prvo prolazi kroz COO conversation sloj koji odlučuje da li je upit `ready_for_translation`. Ako prompt ne izgleda kao system-query / izvršiv upit, endpoint može vratiti UX tekst (npr. pitanje/pojašnjenje) umjesto JSON output contracta agenta.

- Za smoke/e2e obavezno uključiti system-query frazu tipa: `Pregledaj stanje sistema ...` (ili sličan kanonski primjer: `Daj sistemski snapshot ...`) da request prođe gate i dođe do routinga/execution.

Primjer request body-ja koji prolazi gate:

```json
{
	"text": "Pregledaj stanje sistema. Draft sales outreach followup email.",
	"context": {},
	"identity_pack": {"user_id": "test"},
	"snapshot": {},
	"preferred_agent_id": "revenue_growth_operator"
}
```

```powershell
# Offline/deterministic smoke (no real OpenAI calls)
$env:OPENAI_API_MODE = "assistants"; $env:REVENUE_GROWTH_OPERATOR_ASSISTANT_ID = "asst_test_revenue"; python .\tools\smoke_revenue_growth_operator_adnan_ai_input.py

# Pytest e2e smoke (runs both assistants + responses modes offline)
pytest -q -s tests\test_smoke_revenue_growth_operator_adnan_ai_input.py
```

## JobRunner CLI (SSOT templates)

- Notifikacija = chat output + (opcionalno) handoff:* artefakt kad `emit_handoff_log` može proći kroz metadata do postojećeg ExecutionOrchestrator hook-a; trenutno `scripts/jobrunner_cli.py` ne prosljeđuje `emit_handoff_log` u payload metadata (CLI-inert).
- Planned tools su blokirani u ExecutionOrchestrator kao `tool_not_executable` (nema izvršavanja planned/non-MVP tool-ova).

Primjeri inputs fajlova (za JT-OPS-02/03):

- `docs/examples/inputs_ops_daily_brief.json`
- `docs/examples/inputs_ops_snapshot_health.json`

## How to make Dept Ops actually useful

Dept Ops (`dept_ops`) je striktno read-only (tool allowlist: `read_only.query`) + proposal-only Notion writes (dry-run + requires approval). Realni izvještaji dolaze isključivo iz postojećeg Notion knowledge snapshot-a.

### 1) Refresh snapshot (SSOT)

- Pokreni `refresh_snapshot` kroz postojeći orchestrator/approval flow.
- Snapshot mora imati `ready:true` da bi `ops.*` modovi imali smislen output.

### 2) Full Notion visibility = env varovi (db_key mapping)

Snapshot automatski uključuje SVE env varove oblika:

- `NOTION_<LOGICAL>_DB_ID`
- `NOTION_<LOGICAL>_DATABASE_ID`

gdje `db_key = <logical>.lower()`.

Preporučeni (bez hardkodiranja ID-eva):

- `NOTION_GOALS_DB_ID`
- `NOTION_TASKS_DB_ID`
- `NOTION_PROJECTS_DB_ID`
- `NOTION_KPI_DATABASE_ID` (ili `NOTION_KPI_DB_ID`)
- `NOTION_AGENT_EXCHANGE_DB_ID`
- `NOTION_AGENT_PROJECT_DB_ID`
- `NOTION_AI_SUMMARY_DB_ID`

Ako neki DB nije u snapshot-u → to je deployment/config problem: dodaj odgovarajući `NOTION_<LOGICAL>_DB_ID` / `_DATABASE_ID` pa refresh snapshot.

### 3) Snapshot fields (production-safe)

Snapshot exportuje samo allowlisted `item.fields` (nema full Notion dump). Tipovi u `fields` su normalizovani i capped (anti-bloat): string/number/boolean/date-range/list[str]. Ako je nešto preveliko → truncation + `item.truncated=true`.

### 4) KPI preview ograničenje

`ops.kpi_weekly_summary_preview` radi samo ako KPI rows imaju numerička polja u snapshot-u (number/formula/rollup koji rezultiraju brojem). Ako toga nema, vraća `missing_reason=no_numeric_kpi_fields_in_snapshot` (expected).

### 5) Planned tools

Planned tools ostaju blokirani; Dept Ops je read-only + proposals. Nema write izvršavanja bez approval.

## 0) Pre-requisites
- `DATABASE_URL` mora biti postavljen (Postgres).
- Alembic migracije moraju biti na `head`.

## 1) Migracije
```powershell
## DEV (PowerShell)
$env:DATABASE_URL = "postgresql+psycopg://admin:password@localhost:5432/alignment_db"  # dev example
python -m alembic upgrade head

## Recommended (script): runs upgrade + verifies required tables without printing secrets
.\scripts\db_migrate.ps1

## Docker verify (replace container name if different)
docker exec -it adnan-pg psql -U admin -d alignment_db -c "select to_regclass('public.alembic_version'), to_regclass('public.identity_root');"
docker exec -it adnan-pg psql -U admin -d alignment_db -c "\\dt"
```
