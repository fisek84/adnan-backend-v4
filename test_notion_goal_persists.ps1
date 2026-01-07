Param(
  [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

Write-Host "=== NOTION GOAL PERSISTENCE TEST START ==="

function Dump-Json($label, $obj) {
  Write-Host ("--- {0} ---" -f $label)
  Write-Host ($obj | ConvertTo-Json -Depth 50)
  Write-Host ("--- END {0} ---" -f $label)
}

function Approve-IfBlocked($resp) {
  if ($null -eq $resp) { throw "Approve-IfBlocked received null response" }

  if ($resp.execution_state -eq "BLOCKED") {
    if (-not $resp.approval_id) {
      Dump-Json "BLOCKED RESPONSE (missing approval_id)" $resp
      throw "execution_state=BLOCKED but approval_id missing"
    }

    Write-Host "Approving approval_id=$($resp.approval_id) ..."
    $approved = Invoke-RestMethod `
      -Method POST `
      -Uri "$BaseUrl/api/ai-ops/approval/approve" `
      -ContentType "application/json" `
      -Body (@{ approval_id = $resp.approval_id } | ConvertTo-Json -Depth 5)

    return $approved
  }

  return $resp
}

function Execute-Raw-And-Approve($commandObj) {
  if ($null -eq $commandObj) { throw "Execute-Raw-And-Approve received null command" }

  # IMPORTANT (canon): do not construct/alter payload; send the command object exactly as returned.
  $body = $commandObj | ConvertTo-Json -Depth 50

  $resp = Invoke-RestMethod `
    -Method POST `
    -Uri "$BaseUrl/api/execute/raw" `
    -ContentType "application/json" `
    -Body $body

  $resp = Approve-IfBlocked $resp
  return $resp
}

function Get-SnapshotResult($resp) {
  if ($null -eq $resp) { return $null }

  if ($resp.result) { return $resp.result }
  if ($resp.execution -and $resp.execution.result) { return $resp.execution.result }
  if ($resp.data -and $resp.data.result) { return $resp.data.result }

  return $null
}

function Get-TotalGoals($snapshotResult) {
  if ($null -eq $snapshotResult) { return $null }

  # Prefer explicit counters if present
  if ($snapshotResult.PSObject.Properties.Name -contains "total_goals") { return $snapshotResult.total_goals }
  if ($snapshotResult.PSObject.Properties.Name -contains "totalGoals") { return $snapshotResult.totalGoals }
  if ($snapshotResult.snapshot -and ($snapshotResult.snapshot.PSObject.Properties.Name -contains "total_goals")) { return $snapshotResult.snapshot.total_goals }
  if ($snapshotResult.summary -and ($snapshotResult.summary.PSObject.Properties.Name -contains "total_goals")) { return $snapshotResult.summary.total_goals }

  # Fallback: derive from arrays if present
  if ($snapshotResult.goals) { return @($snapshotResult.goals).Count }
  if ($snapshotResult.snapshot -and $snapshotResult.snapshot.goals) { return @($snapshotResult.snapshot.goals).Count }

  return $null
}

function Get-ErrorsArray($snapshotResult) {
  if ($null -eq $snapshotResult) { return @() }

  if ($snapshotResult.errors) { return @($snapshotResult.errors) }
  if ($snapshotResult.snapshot -and $snapshotResult.snapshot.errors) { return @($snapshotResult.snapshot.errors) }
  if ($snapshotResult.summary -and $snapshotResult.summary.errors) { return @($snapshotResult.summary.errors) }

  return @()
}

# 1) Create goal (via /api/execute) -> if BLOCKED, execute proposed_commands canonically via /api/execute/raw + approve
$payload = @{ text = 'kreiraj cilj "Test Notion persist cilj" status Aktivan priority Visok' } | ConvertTo-Json -Depth 5

$create = Invoke-RestMethod `
  -Method POST `
  -Uri "$BaseUrl/api/execute" `
  -ContentType "application/json" `
  -Body $payload

if ($create.execution_state -ne "COMPLETED" -and $create.execution_state -ne "BLOCKED") {
  Dump-Json "CREATE RESPONSE" $create
  throw "EXPECTED COMPLETED or BLOCKED, got: $($create.execution_state)"
}

Write-Host "Create execution_state=$($create.execution_state)"

if ($create.execution_state -eq "BLOCKED") {
  # Canonical path: take proposed_commands returned by backend and send each as-is to /api/execute/raw
  if ($create.proposed_commands -and @($create.proposed_commands).Count -gt 0) {
    Write-Host ("Create returned {0} proposed_commands; executing via /api/execute/raw ..." -f @($create.proposed_commands).Count)

    foreach ($cmd in $create.proposed_commands) {
      $exec = Execute-Raw-And-Approve $cmd
      if ($exec.execution_state -ne "COMPLETED") {
        Dump-Json "EXECUTE/RAW RESULT (NOT COMPLETED)" $exec
        throw "Expected execute/raw COMPLETED, got: $($exec.execution_state)"
      }
    }
  }
  elseif ($create.approval_id) {
    # Legacy compatibility: some versions may gate /api/execute directly with approval_id
    Write-Host "Create is BLOCKED with approval_id; approving ..."
    $create = Approve-IfBlocked $create
    if ($create.execution_state -ne "COMPLETED") {
      Dump-Json "CREATE APPROVED (NOT COMPLETED)" $create
      throw "Create approval not COMPLETED, got: $($create.execution_state)"
    }
  }
  else {
    Dump-Json "CREATE BLOCKED (NO proposed_commands/approval_id)" $create
    throw "Create is BLOCKED but neither proposed_commands nor approval_id present"
  }
}

# 2) Force refresh_snapshot via /api/execute/raw
$refreshPayload = @{
  command   = "refresh_snapshot"
  intent    = "refresh_snapshot"
  params    = @{ source = "test_notion_goal_persists" }
  initiator = "ceo"
  read_only = $false
  metadata  = @{ source = "ps_test"; canon = "CEO_CONSOLE_APPROVAL_GATED_EXECUTION" }
}

Write-Host "Calling refresh_snapshot via /api/execute/raw ..."

$refresh = Invoke-RestMethod `
  -Method POST `
  -Uri "$BaseUrl/api/execute/raw" `
  -ContentType "application/json" `
  -Body ($refreshPayload | ConvertTo-Json -Depth 10)

Write-Host "refresh_snapshot returned execution_state=$($refresh.execution_state)"

$refresh = Approve-IfBlocked $refresh
Write-Host "approve returned execution_state=$($refresh.execution_state)"

if ($refresh.execution_state -ne "COMPLETED") {
  Dump-Json "REFRESH RESPONSE (NOT COMPLETED)" $refresh
  throw "refresh_snapshot not COMPLETED, got: $($refresh.execution_state)"
}

# 3) Assertions on snapshot result
$snapshot = Get-SnapshotResult $refresh
if (-not $snapshot) {
  Dump-Json "REFRESH RESPONSE (MISSING RESULT)" $refresh
  throw "Missing refresh.result (or equivalent wrapper)"
}

$totalGoals = Get-TotalGoals $snapshot
$errors = Get-ErrorsArray $snapshot

Write-Host ("Snapshot result: total_goals={0}, errors_count={1}" -f $totalGoals, @($errors).Count)

# Log errors (but do NOT fail test for unrelated snapshot errors)
if (@($errors).Count -gt 0) {
  Write-Host ("NOTE: snapshot has non-blocking errors (showing first 5):")
  @($errors | Select-Object -First 5) | ForEach-Object { Write-Host (" - {0}" -f $_) }
}

# Fail ONLY on goals DB errors
$goalsErrorKeys = @(
  "active_goals__error",
  "blocked_goals__error",
  "completed_goals__error",
  "goals__error"
)

$hasGoalsDbError = $false
foreach ($k in $goalsErrorKeys) {
  if ($errors -contains $k) { $hasGoalsDbError = $true }
}

if ($hasGoalsDbError) {
  Dump-Json "SNAPSHOT RESULT (GOALS DB ERRORS)" $snapshot
  throw "Snapshot reports goals DB errors: $($errors -join ', ')"
}

# Must have at least 1 goal
if ($null -eq $totalGoals) {
  Dump-Json "SNAPSHOT RESULT (MISSING total_goals)" $snapshot
  throw "Expected snapshot to include total_goals (or equivalent), got: null"
}

if ([int]$totalGoals -lt 1) {
  Dump-Json "SNAPSHOT RESULT (TOTAL < 1)" $snapshot
  throw "Expected total_goals >= 1 after create, got: $totalGoals"
}

Write-Host "=== NOTION GOAL PERSISTENCE TEST PASSED ==="
