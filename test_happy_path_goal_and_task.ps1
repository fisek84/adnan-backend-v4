Param(
  [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

Write-Host "=== GOAL + TASK HAPPY PATH START ==="

# 1) CEO input -> accept BLOCKED (approval gated) OR COMPLETED (auto-approved)
$payload = @{
  text = 'kreiraj cilj "Test kombinovani cilj" status Aktivan priority Visok i task "Test povezani task" status To Do priority Visok'
} | ConvertTo-Json -Depth 5

$r = Invoke-RestMethod `
  -Method POST `
  -Uri "$BaseUrl/api/execute" `
  -ContentType "application/json" `
  -Body $payload

if ($r.execution_state -ne "BLOCKED" -and $r.execution_state -ne "COMPLETED") {
  throw "EXPECTED BLOCKED or COMPLETED, got: $($r.execution_state)"
}

# If BLOCKED: must approve
if ($r.execution_state -eq "BLOCKED") {

  if (-not $r.approval_id) {
    throw "approval_id missing"
  }

  $approval = $r.approval_id
  Write-Host "BLOCKED with approval_id=$approval"

  # 2) Approval must exist (LIST-based)
  $pending = Invoke-RestMethod `
    -Method GET `
    -Uri "$BaseUrl/api/ai-ops/approval/pending"

  $approvalIds = $pending.approvals | ForEach-Object { $_.approval_id }

  if (-not ($approvalIds -contains $approval)) {
    throw "approval not found in pending list"
  }

  Write-Host "Approval is pending"

  # 3) Approve
  $final = Invoke-RestMethod `
    -Method POST `
    -Uri "$BaseUrl/api/ai-ops/approval/approve" `
    -ContentType "application/json" `
    -Body (@{ approval_id = $approval } | ConvertTo-Json)

  if ($final.execution_state -ne "COMPLETED") {
    throw "EXPECTED COMPLETED, got: $($final.execution_state)"
  }

} else {
  # COMPLETED path: treat initial response as final
  $final = $r
  Write-Host "COMPLETED immediately (no approval step)"
}

# Hard success check (only what we can assert generically)
if ($final.result -and ($final.result.ok -eq $false)) {
  throw "Execution completed but result.ok=false"
}

Write-Host "GOAL + TASK HAPPY PATH PASSED (state=$($r.execution_state))"
