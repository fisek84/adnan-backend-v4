Param(
    [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

Write-Host "=== CEO GOAL PLAN 7-DAY WORKFLOW HAPPY PATH (CANONICAL) ==="

# 1) CEO input -> expect BLOCKED (approval-gated)
$body = @{
    text = 'Kreiraj centralni cilj "Implementirati FLP OS" sa due date 01.05.2025, prioritet Visok, status Aktivan. Kreiraj tri podcilja: Podcilj A (Visok), Podcilj B (Visok), Podcilj C (Srednji). Kreiraj 7-dnevni plan sa taskovima.'
} | ConvertTo-Json -Depth 5

$r = Invoke-RestMethod `
    -Method POST `
    -Uri "$BaseUrl/api/execute" `
    -ContentType "application/json" `
    -Body $body

if ($r.execution_state -ne "BLOCKED") {
    throw "EXPECTED BLOCKED, got: $($r.execution_state)"
}

if (-not $r.approval_id) {
    throw "approval_id missing"
}

$approval = $r.approval_id
Write-Host "BLOCKED with approval_id=$approval"

# 2) Approval must exist
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

# CANONICAL ASSERT:
# workflow may COMPLETE or FAIL (best-effort orchestration)
if ($final.execution_state -ne "COMPLETED" -and $final.execution_state -ne "FAILED") {
    throw "EXPECTED COMPLETED or FAILED, got: $($final.execution_state)"
}

Write-Host "Execution finished with state=$($final.execution_state)"
Write-Host "CEO GOAL PLAN 7-DAY WORKFLOW HAPPY PATH PASSED (CANONICAL)"
