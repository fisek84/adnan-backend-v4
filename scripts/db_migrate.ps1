<#
DEV TOOLING: Run Alembic migrations and verify required tables.

- Requires: DATABASE_URL env var
- Never prints the full DATABASE_URL (no secrets)

Example (dev only):
  $env:DATABASE_URL = "postgresql+psycopg://admin:password@localhost:5432/alignment_db"
  .\scripts\db_migrate.ps1
#>

$ErrorActionPreference = "Stop"

function Get-SanitizedDbInfo {
    param([string]$DbUrl)

    $code = @'
import json, os
from sqlalchemy.engine import make_url
u = make_url(os.environ["DATABASE_URL"])
out = {
  "driver": u.drivername,
  "host": u.host,
  "port": u.port,
  "database": u.database,
  "username": u.username,
  "has_password": bool(u.password),
}
print(json.dumps(out))
'@

    $env:DATABASE_URL = $DbUrl
    $json = python -c $code
    return ($json | ConvertFrom-Json)
}

function Verify-IdentityRoot {
    param([string]$DbUrl)

    $code = @'
import json, os
import sqlalchemy as sa
from sqlalchemy.engine import make_url
url = os.environ["DATABASE_URL"]
engine = sa.create_engine(url, pool_pre_ping=True, future=True)
with engine.begin() as conn:
    row = conn.execute(sa.text("select to_regclass('public.alembic_version') as alembic_version, to_regclass('public.identity_root') as identity_root"))
    r = row.fetchone()
print(json.dumps({"alembic_version": r[0], "identity_root": r[1]}))
'@

    $env:DATABASE_URL = $DbUrl
    $json = python -c $code
    return ($json | ConvertFrom-Json)
}

$dbUrl = ($env:DATABASE_URL | ForEach-Object { $_.Trim() })
if (-not $dbUrl) {
    Write-Host "DATABASE_URL is not set." -ForegroundColor Yellow
    Write-Host "Set it in your shell (dev example):" -ForegroundColor Yellow
    Write-Host "  `$env:DATABASE_URL=\"postgresql+psycopg://admin:password@localhost:5432/alignment_db\"" -ForegroundColor Yellow
    exit 1
}

$info = Get-SanitizedDbInfo -DbUrl $dbUrl
Write-Host "DB target:" -ForegroundColor Cyan
Write-Host ("  driver={0} host={1} port={2} db={3} user={4} has_password={5}" -f $info.driver, $info.host, $info.port, $info.database, $info.username, $info.has_password)

Write-Host "Running migrations: alembic upgrade head" -ForegroundColor Cyan
python -m alembic upgrade head

$ver = Verify-IdentityRoot -DbUrl $dbUrl
Write-Host "Verification (to_regclass):" -ForegroundColor Cyan
Write-Host ("  public.alembic_version = {0}" -f $ver.alembic_version)
Write-Host ("  public.identity_root   = {0}" -f $ver.identity_root)

if (-not $ver.alembic_version -or -not $ver.identity_root) {
    throw "Migration verification failed: alembic_version and/or identity_root missing."
}

Write-Host "OK: migrations applied and identity_root present." -ForegroundColor Green
