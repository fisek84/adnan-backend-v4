Param(
    [string]$BaseUrl = "http://localhost:8000"
)

Write-Host "=== CEO GOAL PLAN 7-DAY HAPPY PATH ==="

# 1. CEO input -> expect BLOCKED + approval_id
#   Kraća verzija plana (< 400 karaktera) da ne puca na max_length u backendu
$body = '{
  "text": "Kreiraj centralni cilj \"Implementirati FLP OS\" sa due date 01.05.2025, prioritet Visok, status Aktivan. Kreiraj tri podcilja: Podcilj A (prioritet Visok), Podcilj B (prioritet Visok), Podcilj C (prioritet Srednji). Kreiraj 7-dnevni plan: Dan 1: Task 1 (Visok) Dan 2: Task 2 (Visok) Dan 3: Task 3 (Visok) Dan 4: Task 4 (Visok) Dan 5: Task 5 (Srednji) Dan 6: Task 6 (Srednji) Dan 7: Task 7 (Visok)"
}'

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

Write-Host "CEO GOAL PLAN 7-DAY HAPPY PATH PASSED"
