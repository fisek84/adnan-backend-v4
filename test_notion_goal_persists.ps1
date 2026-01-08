Param(
  [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

Write-Host "=== NOTION GOAL PERSISTENCE TEST (CANON: NO refresh_snapshot) START ==="

function Dump-Json($label, $obj) {
  Write-Host ("--- {0} ---" -f $label)
  Write-Host ($obj | ConvertTo-Json -Depth 80)
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

  # CANON: do not construct/alter payload; send the command object exactly as returned.
  $body = $commandObj | ConvertTo-Json -Depth 80

  $resp = Invoke-RestMethod `
    -Method POST `
    -Uri "$BaseUrl/api/execute/raw" `
    -ContentType "application/json" `
    -Body $body

  $resp = Approve-IfBlocked $resp
  return $resp
}

function Get-ExecutionResult($resp) {
  if ($null -eq $resp) { return $null }

  if ($resp.result) { return $resp.result }
  if ($resp.execution -and $resp.execution.result) { return $resp.execution.result }
  if ($resp.data -and $resp.data.result) { return $resp.data.result }

  return $null
}

function Find-NotionCreatedPage($executionResult) {
  if ($null -eq $executionResult) { return $null }

  $candidates = @()
  $candidates += $executionResult
  if ($executionResult.result) { $candidates += $executionResult.result }
  if ($executionResult.output) { $candidates += $executionResult.output }

  foreach ($c in $candidates) {
    if ($null -eq $c) { continue }

    $intent = $null
    if ($c.PSObject.Properties.Name -contains "intent") { $intent = $c.intent }

    $pageId = $null
    if ($c.PSObject.Properties.Name -contains "page_id") { $pageId = $c.page_id }
    if (-not $pageId -and $c.PSObject.Properties.Name -contains "pageId") { $pageId = $c.pageId }

    $url = $null
    if ($c.PSObject.Properties.Name -contains "url") { $url = $c.url }

    $raw = $null
    if ($c.PSObject.Properties.Name -contains "raw") { $raw = $c.raw }

    if (($intent -eq "create_page" -or $intent -eq "create_goal" -or $intent -eq "notion_create_page") -and ($pageId -or $url)) {
      return @{
        intent  = $intent
        page_id = $pageId
        url     = $url
        raw     = $raw
      }
    }

    if (($pageId -or $url)) {
      return @{
        intent  = $intent
        page_id = $pageId
        url     = $url
        raw     = $raw
      }
    }
  }

  return $null
}

# 1) Create goal via /api/execute (may return BLOCKED + proposed_commands or approval_id)
$payload = @{
  text = 'kreiraj cilj "Test Notion persist cilj" status Aktivan priority Visok'
} | ConvertTo-Json -Depth 5

$create = Invoke-RestMethod `
  -Method POST `
  -Uri "$BaseUrl/api/execute" `
  -ContentType "application/json" `
  -Body $payload

if ($create.execution_state -ne "COMPLETED" -and $create.execution_state -ne "BLOCKED") {
  Dump-Json "CREATE RESPONSE (unexpected state)" $create
  throw "EXPECTED COMPLETED or BLOCKED, got: $($create.execution_state)"
}

Write-Host "Create execution_state=$($create.execution_state)"

$lastExec = $create

if ($create.execution_state -eq "BLOCKED") {

  if ($create.proposed_commands -and @($create.proposed_commands).Count -gt 0) {
    Write-Host ("Create returned {0} proposed_commands; executing each via /api/execute/raw ..." -f @($create.proposed_commands).Count)

    foreach ($cmd in $create.proposed_commands) {
      $exec = Execute-Raw-And-Approve $cmd
      $lastExec = $exec

      if ($exec.execution_state -ne "COMPLETED") {
        Dump-Json "EXECUTE/RAW RESULT (NOT COMPLETED)" $exec
        throw "Expected execute/raw COMPLETED, got: $($exec.execution_state)"
      }
    }
  }
  elseif ($create.approval_id) {
    Write-Host "Create is BLOCKED with approval_id; approving ..."
    $create2 = Approve-IfBlocked $create
    $lastExec = $create2

    if ($create2.execution_state -ne "COMPLETED") {
      Dump-Json "CREATE APPROVED (NOT COMPLETED)" $create2
      throw "Create approval not COMPLETED, got: $($create2.execution_state)"
    }
  }
  else {
    Dump-Json "CREATE BLOCKED (NO proposed_commands/approval_id)" $create
    throw "Create is BLOCKED but neither proposed_commands nor approval_id present"
  }
}

# 2) Assert evidence of Notion create (page_id or url) from the completed execution
if ($lastExec.execution_state -ne "COMPLETED") {
  Dump-Json "LAST EXEC (NOT COMPLETED)" $lastExec
  throw "Expected last execution_state=COMPLETED, got: $($lastExec.execution_state)"
}

$execResult = Get-ExecutionResult $lastExec
if (-not $execResult) {
  Dump-Json "LAST EXEC (MISSING result wrapper)" $lastExec
  throw "Missing execution result payload"
}

$created = Find-NotionCreatedPage $execResult
if (-not $created) {
  Dump-Json "EXECUTION RESULT (NO page_id/url found)" $execResult
  throw "Expected Notion create evidence (page_id or url) in execution result, but none found"
}

Write-Host ("Notion create evidence: page_id={0}, url={1}" -f $created.page_id, $created.url)

Write-Host "=== NOTION GOAL PERSISTENCE TEST (CANON) PASSED ==="
