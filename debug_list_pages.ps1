param(
  [Parameter(Mandatory = $true)]
  [string]$DbKey
)

Write-Host "LIST PAGES FOR DB_KEY=$DbKey (RAW + APPROVE)"

# 1) RAW EXECUTE -> BLOCKED
$body = @{
  command = "notion_write"
  intent  = "query_database"
  params  = @{
    db_key         = $DbKey
    property_specs = @{}
  }
} | ConvertTo-Json -Depth 5

$r = Invoke-RestMethod `
  -Method POST `
  -Uri http://localhost:8000/api/execute/raw `
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

# 2) CHECK PENDING
$pending = Invoke-RestMethod `
  -Method GET `
  -Uri http://localhost:8000/api/ai-ops/approval/pending

$approvalIds = $pending.approvals | ForEach-Object { $_.approval_id }

if (-not ($approvalIds -contains $approval)) {
  throw "approval not found in pending list"
}

Write-Host "Approval is pending"

# 3) APPROVE
$approved = Invoke-RestMethod `
  -Method POST `
  -Uri http://localhost:8000/api/ai-ops/approval/approve `
  -ContentType "application/json" `
  -Body (@{ approval_id = $approval } | ConvertTo-Json)

if ($approved.execution_state -ne "COMPLETED") {
  throw "EXPECTED COMPLETED, got: $($approved.execution_state)"
}

Write-Host "Approval completed, dumping result JSON:"
$approved.result | ConvertTo-Json -Depth 10
