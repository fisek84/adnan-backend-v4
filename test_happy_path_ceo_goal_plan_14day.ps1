Param(
    [string]$BaseUrl = "http://localhost:8000"
)

Write-Host "=== CEO GOAL PLAN 14-DAY HAPPY PATH ==="

# Kraća, ali strukturirana verzija plana (goal + 3 subgoala + 14-dnevni plan header + Dan X taskovi)
$body = '{
  "text": "Kreiraj centralni cilj \"Implementirati KPI OS\" sa due date 15.06.2025, prioritet Visok, status Aktivan. Kreiraj tri podcilja: KPI dizajn (prioritet Visok), KPI dashboard (prioritet Visok), KPI reporting (prioritet Srednji). Kreiraj 14-dnevni plan: Dan 1: KPI plan (Visok) Dan 2: Mapirati metrike (Visok) Dan 3: Postaviti dashboard (Visok) Dan 4: Povezati podatke (Srednji) Dan 5: Testirati izvještaje (Srednji) Dan 6: Refinirati KPI (Visok) Dan 7: Finalna provjera (Visok)"
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

Write-Host "CEO GOAL PLAN 14-DAY HAPPY PATH PASSED"
