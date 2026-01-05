Param(
  [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

Write-Host "=== NOTION GOAL PERSISTENCE TEST START ==="

# 1) Create goal (via execute)
$payload = @{
  text = 'kreiraj cilj "Test Notion persist cilj" status Aktivan priority Visok'
} | ConvertTo-Json -Depth 5

$create = Invoke-RestMethod `
  -Method POST `
  -Uri "$BaseUrl/api/execute" `
  -ContentType "application/json" `
  -Body $payload

if ($create.execution_state -ne "COMPLETED" -and $create.execution_state -ne "BLOCKED") {
  throw "EXPECTED COMPLETED or BLOCKED, got: $($create.execution_state)"
}

Write-Host "Create execution_state=$($create.execution_state)"

# 2) Force refresh_snapshot via execute/raw
$refreshPayload = @{
  command   = "refresh_snapshot"
  intent    = "refresh_snapshot"
  params    = @{ source = "test_notion_goal_persists" }
  initiator = "ceo"
  read_only = $false
  metadata  = @{ source = "ps_test"; canon = "CEO_CONSOLE_APPROVAL_GATED_EXECUTION" }
} | ConvertTo-Json -Depth 10

Write-Host "Calling refresh_snapshot via /api/execute/raw ..."

try {
  $refresh = Invoke-RestMethod `
    -Method POST `
    -Uri "$BaseUrl/api/execute/raw" `
    -ContentType "application/json" `
    -Body $refreshPayload
  Write-Host "refresh_snapshot returned execution_state=$($refresh.execution_state)"
} catch {
  throw "refresh_snapshot call failed: $($_.Exception.Message)"
}

# If refresh is gated, approve it
if ($refresh.execution_state -eq "BLOCKED") {
  if (-not $refresh.approval_id) { throw "refresh BLOCKED but approval_id missing" }

  Write-Host "Approving refresh approval_id=$($refresh.approval_id) ..."

  try {
    $refresh = Invoke-RestMethod `
      -Method POST `
      -Uri "$BaseUrl/api/ai-ops/approval/approve" `
      -ContentType "application/json" `
      -Body (@{ approval_id = $refresh.approval_id } | ConvertTo-Json)
    Write-Host "approve returned execution_state=$($refresh.execution_state)"
  } catch {
    throw "approve failed: $($_.Exception.Message)"
  }
}

if ($refresh.execution_state -ne "COMPLETED") {
  throw "refresh_snapshot not COMPLETED, got: $($refresh.execution_state)"
}

# 3) Assertions on snapshot result (based on your real response schema)
if (-not $refresh.result) { throw "Missing refresh.result" }

Write-Host ("Snapshot result: total_goals={0}, errors={1}" -f $refresh.result.total_goals, ($refresh.result.errors -join ","))

# must not have goal errors
$errs = @()
if ($refresh.result.errors) { $errs = $refresh.result.errors }

if ($errs -contains "active_goals__error" -or $errs -contains "blocked_goals__error" -or $errs -contains "completed_goals__error") {
  throw "Snapshot still reports goals DB errors: $($errs -join ', ')"
}

# must have at least 1 goal
if ($refresh.result.total_goals -lt 1) {
  throw "Expected total_goals >= 1 after create, got: $($refresh.result.total_goals)"
}

Write-Host "=== NOTION GOAL PERSISTENCE TEST PASSED ==="
