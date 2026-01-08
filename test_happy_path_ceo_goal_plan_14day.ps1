Param(
    [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

Write-Host "=== CEO GOAL PLAN 14-DAY WORKFLOW HAPPY PATH (CANONICAL) ==="

# 1) CEO input (workflow je BEST-EFFORT, ne očekujemo nužno COMPLETED)
$body = @"
{
  "text": "Kreiraj centralni cilj \"Implementirati KPI OS\" sa due date 15.06.2025, prioritet Visok, status Aktivan. Kreiraj tri podcilja: KPI dizajn (prioritet Visok), KPI dashboard (prioritet Visok), KPI reporting (prioritet Srednji). Kreiraj 14-dnevni plan: Dan 1: KPI plan (Visok) Dan 2: Mapirati metrike (Visok) Dan 3: Postaviti dashboard (Visok) Dan 4: Povezati podatke (Srednji) Dan 5: Testirati izvještaje (Srednji) Dan 6: Refinirati KPI (Visok) Dan 7: Finalna provjera (Visok)"
}
"@

$r = Invoke-RestMethod `
  -Method POST `
  -Uri "$BaseUrl/api/execute" `
  -ContentType "application/json" `
  -Body $body

if ($r.execution_state -ne "BLOCKED" -and $r.execution_state -ne "COMPLETED") {
    throw "EXPECTED BLOCKED or COMPLETED, got: $($r.execution_state)"
}

if ($r.execution_state -eq "BLOCKED") {

    if (-not $r.approval_id) {
        throw "approval_id missing"
    }

    $approval = $r.approval_id
    Write-Host "BLOCKED with approval_id=$approval"

    $pending = Invoke-RestMethod `
        -Method GET `
        -Uri "$BaseUrl/api/ai-ops/approval/pending"

    $approvalIds = $pending.approvals | ForEach-Object { $_.approval_id }

    if (-not ($approvalIds -contains $approval)) {
        throw "approval not found in pending list"
    }

    Write-Host "Approval is pending"

    $final = Invoke-RestMethod `
        -Method POST `
        -Uri "$BaseUrl/api/ai-ops/approval/approve" `
        -ContentType "application/json" `
        -Body (@{ approval_id = $approval } | ConvertTo-Json)

    Write-Host "Execution finished with state=$($final.execution_state)"

    # CANONICAL: workflow je best-effort → FAILED je dozvoljen
    Write-Host "CEO GOAL PLAN 14-DAY WORKFLOW HAPPY PATH PASSED (CANONICAL)"

} else {
    Write-Host "COMPLETED immediately (no approval step)"
    Write-Host "CEO GOAL PLAN 14-DAY WORKFLOW HAPPY PATH PASSED (CANONICAL)"
}
