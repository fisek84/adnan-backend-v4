Write-Host "SIMPLE CEO COMMAND TEST START"

function Invoke-EvoliaCommand {
    param(
        [string]$Text
    )

    Write-Host ""
    Write-Host "=== CEO INPUT: $Text ==="

    $r = Invoke-RestMethod `
      -Method POST `
      -Uri http://localhost:8000/api/execute `
      -ContentType "application/json" `
      -Body (@{ text = $Text } | ConvertTo-Json)

    if ($r.execution_state -ne "BLOCKED") {
      throw "EXPECTED BLOCKED, got: $($r.execution_state)"
    }

    if (-not $r.approval_id) {
      throw "approval_id missing"
    }

    $approval = $r.approval_id
    Write-Host "BLOCKED with approval_id=$approval"

    $pending = Invoke-RestMethod `
      -Method GET `
      -Uri http://localhost:8000/api/ai-ops/approval/pending

    $approvalIds = $pending.approvals | ForEach-Object { $_.approval_id }

    if (-not ($approvalIds -contains $approval)) {
      throw "approval not found in pending list"
    }

    Write-Host "Approval is pending"

    $approved = Invoke-RestMethod `
      -Method POST `
      -Uri http://localhost:8000/api/ai-ops/approval/approve `
      -ContentType "application/json" `
      -Body (@{ approval_id = $approval } | ConvertTo-Json)

    if ($approved.execution_state -ne "COMPLETED") {
      throw "EXPECTED COMPLETED, got: $($approved.execution_state)"
    }

    Write-Host "Approval completed"
}

$Text = Read-Host "Unesi CEO komandu (npr: prikazi taskove sa statusom In Progress i prioritetom High)"
Invoke-EvoliaCommand -Text $Text

Write-Host ""
Write-Host "SIMPLE CEO COMMAND TEST FINISHED"
