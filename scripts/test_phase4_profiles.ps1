# scripts/test_phase4_profiles.ps1
$ErrorActionPreference = "Stop"

function Assert($cond, $msg) { if (-not $cond) { throw $msg } }

Write-Host "=== FAZA 4: PROFILES SMOKE SUITE ==="

# -------------------------
# A) HAPPY PATH
# -------------------------
Write-Host "`n[A] HAPPY_PATH -> immutable test_happy_path.ps1 MUST PASS"
powershell -ExecutionPolicy Bypass -File .\scripts\start_server_profile.ps1 -Profile HAPPY_PATH
powershell -ExecutionPolicy Bypass -File .\test_happy_path.ps1
Write-Host "[A] PASS"

# -------------------------
# B) CEO ENFORCEMENT
# -------------------------
Write-Host "`n[B] CEO_ENFORCEMENT -> approve without token=403, with token=COMPLETED"
powershell -ExecutionPolicy Bypass -File .\scripts\start_server_profile.ps1 -Profile CEO_ENFORCEMENT

$r = Invoke-RestMethod -Method POST -Uri http://localhost:8000/api/execute -ContentType "application/json" -Body '{"text":"create goal Phase4 Token Smoke"}'
Assert ($r.execution_state -eq "BLOCKED") "Expected BLOCKED"
$approval = $r.approval_id
Assert ($approval) "approval_id missing"

# without token => 403
try {
  Invoke-RestMethod -Method POST -Uri http://localhost:8000/api/ai-ops/approval/approve -ContentType "application/json" -Body (@{approval_id=$approval}|ConvertTo-Json)
  throw "UNEXPECTED: approve without token succeeded"
} catch {
  $code = $_.Exception.Response.StatusCode.value__
  $msg = $_.ErrorDetails.Message
  Assert ($code -eq 403) "Expected 403, got $code"
  Assert ($msg -match "CEO token required") "Expected CEO token required message"
}

# with token => COMPLETED
$ok = Invoke-RestMethod -Method POST -Uri http://localhost:8000/api/ai-ops/approval/approve `
  -Headers @{"X-CEO-Token"="secret123"} -ContentType "application/json" -Body (@{approval_id=$approval}|ConvertTo-Json)

Assert ($ok.execution_state -eq "COMPLETED") "Expected COMPLETED"
Write-Host "[B] PASS"

# -------------------------
# C) OPS SAFE MODE
# -------------------------
Write-Host "`n[C] OPS_SAFE_MODE -> writes blocked, reads ok"
powershell -ExecutionPolicy Bypass -File .\scripts\start_server_profile.ps1 -Profile OPS_SAFE_MODE

$r2 = Invoke-RestMethod -Method POST -Uri http://localhost:8000/api/execute -ContentType "application/json" -Body '{"text":"create goal Phase4 SafeMode Smoke"}'
$approval2 = $r2.approval_id
Assert ($approval2) "approval_id missing"

# approve must 403
try {
  Invoke-RestMethod -Method POST -Uri http://localhost:8000/api/ai-ops/approval/approve -ContentType "application/json" -Body (@{approval_id=$approval2}|ConvertTo-Json)
  throw "UNEXPECTED: approve succeeded in OPS_SAFE_MODE"
} catch {
  $code = $_.Exception.Response.StatusCode.value__
  $msg = $_.ErrorDetails.Message
  Assert ($code -eq 403) "Expected 403, got $code"
  Assert ($msg -match "OPS_SAFE_MODE enabled") "Expected OPS_SAFE_MODE enabled message"
}

# reads ok
$pending = Invoke-RestMethod -Method GET -Uri http://localhost:8000/api/ai-ops/approval/pending
Assert ($pending.read_only -eq $true) "Expected read_only=True on pending"

$health = Invoke-RestMethod -Method GET -Uri http://localhost:8000/api/ai-ops/agents/health
Assert ($health.read_only -eq $true) "Expected read_only=True on agents/health"

# one extra WRITE check (metrics/persist) must 403
try {
  Invoke-RestMethod -Method POST -Uri http://localhost:8000/api/ai-ops/metrics/persist -ContentType "application/json" -Body "{}"
  throw "UNEXPECTED: metrics/persist succeeded in OPS_SAFE_MODE"
} catch {
  $code = $_.Exception.Response.StatusCode.value__
  Assert ($code -eq 403) "Expected 403 on metrics/persist in OPS_SAFE_MODE"
}

Write-Host "[C] PASS"

Write-Host "`n=== FAZA 4 ZAVRŠENA ==="
