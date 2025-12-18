Param(
    [string]$BaseUrl = "http://localhost:8000"
)

Write-Host "=== GOAL + TASK HAPPY PATH START ==="

# 1. CEO input -> expect BLOCKED + approval_id
$payload = @{
  text = 'kreiraj cilj "Test kombinovani cilj" status Aktivan priority Visok i task "Test povezani task" status To Do priority Visok'
} | ConvertTo-Json -Depth 5

$r = Invoke-RestMethod `
  -Method POST `
  -Uri "$BaseUrl/api/execute" `
  -ContentType "application/json" `
  -Body $payload

if ($r.execution_state -ne "BLOCKED") {
  throw "EXPECTED BLOCKED, got: $($r.execution_state)"
}

if (-not $r.approval_id) {
  throw "approval_id missing"
}

$approval = $r.approval_id
Write-Host "BLOCKED with approval_id=$approval"

# 2. Approval must exist (LIST-based)
$pending = Invoke-RestMethod `
  -Method GET `
  -Uri "$BaseUrl/api/ai-ops/approval/pending"

$approvalIds = $pending.approvals | ForEach-Object { $_.approval_id }

if (-not ($approvalIds -contains $approval)) {
  throw "approval not found in pending list"
}

Write-Host "Approval is pending"

# 3. Approve
$approved = Invoke-RestMethod `
  -Method POST `
  -Uri "$BaseUrl/api/ai-ops/approval/approve" `
  -ContentType "application/json" `
  -Body (@{
      approval_id = $approval
    } | ConvertTo-Json)

if ($approved.execution_state -ne "COMPLETED") {
  throw "EXPECTED COMPLETED, got: $($approved.execution_state)"
}

Write-Host "GOAL + TASK HAPPY PATH PASSED"
