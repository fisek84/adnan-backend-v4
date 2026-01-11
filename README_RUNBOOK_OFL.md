# Outcome Feedback Loop (OFL) — Runbook

## 0) Pre-requisites
- `DATABASE_URL` mora biti postavljen (Postgres).
- Alembic migracije moraju biti na `head`.

## 1) Migracije
```powershell
alembic upgrade head
