Param(
    [string]$BaseUrl = "http://localhost:8000"
)

Write-Host "=== KPI WEEKLY SUMMARY HAPPY PATH ==="

# 1) CEO input -> očekujemo BLOCKED + approval_id
$body = '{
  "text": "daj mi weekly KPI rezime za ovu sedmicu"
}'

$r = Invoke-RestMethod `
  -Method POST `
  -Uri "$BaseUrl/api/execute" `
  -ContentType "application/json" `
  -Body $body

if ($r.execution_state -ne "BLOCKED") {
  Write-Host "`n--- /api/execute RESPONSE ---"
  $r | ConvertTo-Json -Depth 30
  Write-Host "--- END /api/execute RESPONSE ---`n"
  throw "EXPECTED BLOCKED, got: $($r.execution_state)"
}

if (-not $r.approval_id) {
  Write-Host "`n--- /api/execute RESPONSE ---"
  $r | ConvertTo-Json -Depth 30
  Write-Host "--- END /api/execute RESPONSE ---`n"
  throw "approval_id missing"
}

$approval = $r.approval_id
Write-Host "BLOCKED with approval_id=$approval"

# 2) Approval mora biti u pending listi
$pending = Invoke-RestMethod `
  -Method GET `
  -Uri "$BaseUrl/api/ai-ops/approval/pending"

$approvalIds = $pending.approvals | ForEach-Object { $_.approval_id }

if (-not ($approvalIds -contains $approval)) {
  Write-Host "`n--- /api/ai-ops/approval/pending RESPONSE ---"
  $pending | ConvertTo-Json -Depth 30
  Write-Host "--- END pending RESPONSE ---`n"
  throw "approval not found in pending list"
}

Write-Host "Approval is pending"

# 3) Approve -> očekujemo COMPLETED
$approveBody = (@{
  approval_id = $approval
} | ConvertTo-Json)

$approved = Invoke-RestMethod `
  -Method POST `
  -Uri "$BaseUrl/api/ai-ops/approval/approve" `
  -ContentType "application/json" `
  -Body $approveBody

if ($approved.execution_state -ne "COMPLETED") {
  Write-Host "`n--- /api/ai-ops/approval/approve RESPONSE (NOT COMPLETED) ---"
  $approved | ConvertTo-Json -Depth 50
  Write-Host "--- END approve RESPONSE ---`n"

  $eid = $approved.execution_id
  $etype = $approved.failure.error_type
  $reason = $approved.failure.reason

  if (-not $eid) { $eid = "(missing execution_id)" }
  if (-not $etype) { $etype = "(missing error_type)" }
  if (-not $reason) { $reason = "(missing reason)" }

  throw "EXPECTED COMPLETED, got: $($approved.execution_state) | execution_id=$eid | $etype | $reason"
}

Write-Host "KPI WEEKLY SUMMARY HAPPY PATH PASSED"
