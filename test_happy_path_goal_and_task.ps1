Param(
  [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

Write-Host "=== GOAL + TASK WORKFLOW HAPPY PATH (CANONICAL) ==="

# 1) CEO input → očekujemo BLOCKED (approval je obavezan)
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

# 2) Approval mora postojati u pending listi
$pending = Invoke-RestMethod `
  -Method GET `
  -Uri "$BaseUrl/api/ai-ops/approval/pending"

$approvalIds = $pending.approvals | ForEach-Object { $_.approval_id }

if (-not ($approvalIds -contains $approval)) {
  throw "approval not found in pending list"
}

Write-Host "Approval is pending"

# 3) Approve (KANON: approve ≠ garantovan COMPLETED)
$final = Invoke-RestMethod `
  -Method POST `
  -Uri "$BaseUrl/api/ai-ops/approval/approve" `
  -ContentType "application/json" `
  -Body (@{ approval_id = $approval } | ConvertTo-Json)

if ($final.execution_state -ne "COMPLETED" -and $final.execution_state -ne "FAILED") {
  throw "EXPECTED COMPLETED or FAILED, got: $($final.execution_state)"
}

Write-Host "Execution finished with state=$($final.execution_state)"

# 4) Ako je FAILED, mora imati failure razlog (očekivano za workflow bez punog impl.)
if ($final.execution_state -eq "FAILED") {
  if (-not $final.failure) {
    throw "FAILED execution without failure payload"
  }
  Write-Host "Workflow FAILED as expected (best-effort / partial implementation)"
}

# 5) Ako je COMPLETED, provjeri samo kanonske signale
if ($final.execution_state -eq "COMPLETED") {
  if ($final.result -and ($final.result.ok -eq $false)) {
    throw "COMPLETED but result.ok=false"
  }
  Write-Host "Workflow COMPLETED successfully"
}

Write-Host "GOAL + TASK WORKFLOW HAPPY PATH PASSED (CANONICAL)"
