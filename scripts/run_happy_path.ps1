# scripts\run_happy_path.ps1
$ErrorActionPreference = "Stop"

# Go to repo root (parent of /scripts)
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

if (-not (Test-Path ".\.env")) { throw ".env not found in repo root" }

# Load .env into process env (simple KEY=VALUE lines; skips comments/blank)
Get-Content ".\.env" | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
  $k, $v = $_ -split '=', 2
  if ($k -and $v) { Set-Item -Path "Env:$k" -Value $v }
}

$env:HAPPY_PATH_LIVE_NOTION = "true"

pytest -q -k test_happy_path_execute_approve -vv -s
exit $LASTEXITCODE
