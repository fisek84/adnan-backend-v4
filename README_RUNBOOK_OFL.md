# Outcome Feedback Loop (OFL) — Runbook

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
