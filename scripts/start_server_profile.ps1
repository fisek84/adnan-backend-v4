# scripts/start_server_profile.ps1
param(
  [Parameter(Mandatory=$true)]
  [ValidateSet("HAPPY_PATH","CEO_ENFORCEMENT","OPS_SAFE_MODE")]
  [string]$Profile
)

. "$PSScriptRoot\_canon_env.ps1"

Stop-Port8000

# Očisti env override da .env ne “ratuje” sa procesom
Remove-Item Env:OPS_SAFE_MODE -ErrorAction SilentlyContinue
Remove-Item Env:CEO_TOKEN_ENFORCEMENT -ErrorAction SilentlyContinue
Remove-Item Env:CEO_APPROVAL_TOKEN -ErrorAction SilentlyContinue

if ($Profile -eq "HAPPY_PATH") {
  $env:OPS_SAFE_MODE="false"
  $env:CEO_TOKEN_ENFORCEMENT="false"
  $env:CEO_APPROVAL_TOKEN="secret123"   # može stajati, enforcement je OFF
}

if ($Profile -eq "CEO_ENFORCEMENT") {
  $env:OPS_SAFE_MODE="false"
  $env:CEO_TOKEN_ENFORCEMENT="true"
  $env:CEO_APPROVAL_TOKEN="secret123"
}

if ($Profile -eq "OPS_SAFE_MODE") {
  $env:OPS_SAFE_MODE="true"
  $env:CEO_TOKEN_ENFORCEMENT="false"
  $env:CEO_APPROVAL_TOKEN="secret123"
}

Write-Host "Starting server with profile=$Profile"
Write-Host "OPS_SAFE_MODE=$env:OPS_SAFE_MODE"
Write-Host "CEO_TOKEN_ENFORCEMENT=$env:CEO_TOKEN_ENFORCEMENT"

# Start uvicorn kao job (isti env je naslijeđen)
if (Get-Job -Name "server8000" -ErrorAction SilentlyContinue) {
  Stop-Job -Name "server8000" -Force -ErrorAction SilentlyContinue
  Remove-Job -Name "server8000" -Force -ErrorAction SilentlyContinue
}

Start-Job -Name "server8000" -ScriptBlock {
  cd C:\adnan-backend-v4
  python -m uvicorn gateway.gateway_server:app --host 127.0.0.1 --port 8000
} | Out-Null

Wait-Port8000

# Sanity snapshot
$s = Invoke-RestMethod -Method GET -Uri http://localhost:8000/api/ceo/console/snapshot
Write-Host "snapshot.ops_safe_mode=$($s.system.ops_safe_mode)"

if ($Profile -eq "OPS_SAFE_MODE" -and $s.system.ops_safe_mode -ne $true) { throw "Snapshot mismatch: expected ops_safe_mode=true" }
if ($Profile -ne "OPS_SAFE_MODE" -and $s.system.ops_safe_mode -ne $false) { throw "Snapshot mismatch: expected ops_safe_mode=false" }

Write-Host "Server READY for profile=$Profile"
