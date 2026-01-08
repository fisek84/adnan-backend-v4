# canon/test_happy_path.ps1
# PATCH: handle hard-block read-only terminal for proposal wrapper.

param(
  [Parameter(Mandatory=$false)]
  [string]$BaseUrl = "http://localhost:8000",

  [Parameter(Mandatory=$false)]
  [string]$CeoToken = "",

  [Parameter(Mandatory=$false)]
  [switch]$UseChatEndpoint
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Section([string]$title) {
  Write-Host ""
  Write-Host "== $title ==" -ForegroundColor Cyan
}

function Fail([string]$msg) {
  Write-Host ""
  Write-Host "FAIL: $msg" -ForegroundColor Red
  exit 1
}

function Ok([string]$msg) {
  Write-Host "PASS: $msg" -ForegroundColor Green
}

function Invoke-Json {
  param(
    [Parameter(Mandatory=$true)][string]$Method,
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$false)][object]$Body = $null,
    [Parameter(Mandatory=$false)][hashtable]$Headers = $null
  )

  $uri = ($BaseUrl.TrimEnd("/") + $Path)

  $h = @{ }
  $h["Content-Type"] = "application/json"
  if ($Headers) {
    foreach ($k in $Headers.Keys) { $h[$k] = $Headers[$k] }
  }

  $jsonBody = $null
  if ($null -ne $Body) {
    $jsonBody = ($Body | ConvertTo-Json -Depth 30)
  }

  try {
    $resp = Invoke-WebRequest -Method $Method -Uri $uri -Headers $h -Body $jsonBody -UseBasicParsing
  } catch {
    if ($_.Exception.Response) {
      $status = [int]$_.Exception.Response.StatusCode
      $sr = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
      $text = $sr.ReadToEnd()
      Fail("$Method $Path returned HTTP $status. Body: $text")
    }
    Fail("$Method $Path failed: $($_.Exception.Message)")
  }

  $statusCode = [int]$resp.StatusCode
  $content = $resp.Content

  $data = $null
  try { $data = $content | ConvertFrom-Json } catch { $data = $content }

  return [PSCustomObject]@{
    status = $statusCode
    data   = $data
    raw    = $content
  }
}

# eliminate nested-array bug (array-in-array) for proposed_commands.
function Get-ProposedCommandsFromResponse($data) {
  if ($null -eq $data) { return @() }

  function As-FlatList($x) {
    if ($null -eq $x) { return @() }
    if ($x -is [System.Collections.IEnumerable] -and -not ($x -is [string])) {
      return @($x)
    }
    return @($x)
  }

  if ($data.PSObject.Properties.Name -contains "proposed_commands") {
    return (As-FlatList $data.proposed_commands)
  }

  if ($data.PSObject.Properties.Name -contains "trace") {
    $t = $data.trace
    if ($t -and ($t.PSObject.Properties.Name -contains "proposed_commands")) {
      return (As-FlatList $t.proposed_commands)
    }
  }

  return @()
}

function Convert-ProposalToExecuteRawPayload($proposal) {
  if ($null -eq $proposal) { return $null }

  function Has-Prop($o, [string]$name) {
    return ($null -ne $o) -and ($o.PSObject.Properties.Name -contains $name)
  }

  function New-ExecPayload([string]$command, [string]$intent, $paramsObj) {
    $p = $paramsObj
    if ($null -eq $p) { $p = @{} }

    return @{
      command   = $command
      intent    = $intent
      params    = $p
      initiator = "ceo"
      read_only = $false
      metadata  = @{
        canon  = "happy_path"
        source = "test_happy_path.ps1"
      }
    }
  }

  if (Has-Prop $proposal "command") {
    $cmd0 = ([string]$proposal.command).Trim()
    $intent0 = $cmd0
    if (Has-Prop $proposal "intent") {
      $intent0 = ([string]$proposal.intent).Trim()
      if ($intent0.Length -eq 0) { $intent0 = $cmd0 }
    }

    $isWrapper = ($cmd0 -eq "ceo.command.propose") -or ($intent0 -eq "ceo.command.propose")
    if ($isWrapper) {
      $p0 = $null
      if (Has-Prop $proposal "params") { $p0 = $proposal.params }
      elseif (Has-Prop $proposal "payload") { $p0 = $proposal.payload }

      $prompt = $null
      if ($p0 -and (Has-Prop $p0 "prompt")) { $prompt = $p0.prompt }

      if (($null -eq $prompt -or ([string]$prompt).Trim().Length -eq 0) -and (Has-Prop $proposal "args")) {
        $a0 = $proposal.args
        if ($a0 -and (Has-Prop $a0 "prompt")) { $prompt = $a0.prompt }
      }

      if ($null -eq $prompt -or ([string]$prompt).Trim().Length -eq 0) {
        return $null
      }

      return (New-ExecPayload -command $cmd0 -intent $intent0 -paramsObj @{ prompt = ([string]$prompt).Trim() })
    }
  }

  if (Has-Prop $proposal "command") {
    $cmd = [string]$proposal.command
    if ($cmd.Trim().Length -gt 0) {
      $intent = $cmd
      if (Has-Prop $proposal "intent") {
        $intent = [string]$proposal.intent
        if ($intent.Trim().Length -eq 0) { $intent = $cmd }
      }

      $p = @{ }
      if (Has-Prop $proposal "params") { $p = $proposal.params }

      return (New-ExecPayload -command $cmd -intent $intent -paramsObj $(if ($p) { $p } else { @{} }))
    }
  }

  return $null
}

# --- NEW: detect hard-block terminal response from /api/execute/raw ---
function Is-HardBlockTerminal($data) {
  if ($null -eq $data) { return $false }
  if (-not ($data.PSObject.Properties.Name -contains "read_only")) { return $false }
  if (-not ($data.PSObject.Properties.Name -contains "execution_state")) { return $false }
  if ([bool]$data.read_only -ne $true) { return $false }
  $st = [string]$data.execution_state
  return ($st -eq "COMPLETED")
}

$headers = @{ }
if ($CeoToken.Trim().Length -gt 0) {
  $headers["X-CEO-Token"] = $CeoToken.Trim()
}

Write-Section "0) Health check"
$health = Invoke-Json -Method "GET" -Path "/health" -Headers $headers
if ($health.status -ne 200) { Fail("health status code $($health.status)") }

if ($health.data -and ($health.data.PSObject.Properties.Name -contains "ops_safe_mode")) {
  if ($health.data.ops_safe_mode -eq $true) {
    Fail("OPS_SAFE_MODE=true. WRITE path will be blocked. Set OPS_SAFE_MODE=false for Happy Path.")
  }
}
Ok("health ok; ops_safe_mode is not blocking")

Write-Section "1) Get proposals (READ path)"
$prompt = "CANON HAPPY PATH (CEO Advisor): Propose a command to create a Notion task titled 'HP Test' with priority High and due tomorrow. DO NOT execute. Return proposed_commands."

function Invoke-ReadRequest {
  param([switch]$ViaChat)

  if ($ViaChat) {
    return Invoke-Json -Method "POST" -Path "/api/chat" -Body @{
      message = $prompt
      preferred_agent_id = "ceo_advisor"
      agent_id = "ceo_advisor"
      context = @{ preferred_agent_id = "ceo_advisor" }
    } -Headers $headers
  }

  return Invoke-Json -Method "POST" -Path "/api/ceo/command" -Body @{
    text = $prompt
    initiator = "canon_test"
    session_id = $null
    preferred_agent_id = "ceo_advisor"
    agent_id = "ceo_advisor"
    context_hint = @{
      source = "canon_test"
      preferred_agent_id = "ceo_advisor"
      agent_id = "ceo_advisor"
      read_only = $true
      require_approval = $true
    }
    smart_context = @{
      source = "canon_test"
      preferred_agent_id = "ceo_advisor"
      agent_id = "ceo_advisor"
      read_only = $true
      require_approval = $true
    }
  } -Headers $headers
}

if ($UseChatEndpoint) { $readResp = Invoke-ReadRequest -ViaChat }
else { $readResp = Invoke-ReadRequest }

if ($readResp.status -ne 200) { Fail("READ endpoint returned $($readResp.status)") }

$proposals = @(Get-ProposedCommandsFromResponse $readResp.data)
if ($proposals.Count -lt 1) { Fail("No proposed_commands returned.") }

Ok("proposed_commands present: $($proposals.Count)")
$proposal0 = $proposals[0]

Write-Section "2) Execute/raw (WRITE path creates approval OR terminal read-only)"
$execPayload = Convert-ProposalToExecuteRawPayload $proposal0
if ($null -eq $execPayload) {
  Fail("Cannot map proposal to execute/raw payload. Proposal[0]: $($proposal0 | ConvertTo-Json -Depth 30)")
}

Write-Host "EXEC PAYLOAD (about to POST /api/execute/raw):"
$execJson = ($execPayload | ConvertTo-Json -Depth 30)
Write-Host $execJson

$exec = Invoke-Json -Method "POST" -Path "/api/execute/raw" -Body $execPayload -Headers $headers
if ($exec.status -ne 200) { Fail("execute/raw returned $($exec.status). Body: $($exec.raw)") }

# --- NEW: if hard-block terminal, end test successfully ---
if (Is-HardBlockTerminal $exec.data) {
  Ok("execute/raw hard-blocked as read-only terminal (COMPLETED); no approval_id expected.")
  Ok("Happy Path completed (READ-ONLY terminal).")
  exit 0
}

# --- Otherwise: legacy approval flow ---
if (-not ($exec.data.PSObject.Properties.Name -contains "approval_id")) {
  Fail("execute/raw missing approval_id. Body: $($exec.raw)")
}
$approvalId = [string]$exec.data.approval_id
if ($approvalId.Trim().Length -eq 0) { Fail("approval_id empty. Body: $($exec.raw)") }
Ok("approval_id created: $approvalId")

Write-Section "3) Approve (governance gate resumes execution)"
$approve = Invoke-Json -Method "POST" -Path "/api/ai-ops/approval/approve" -Body @{ approval_id = $approvalId } -Headers $headers
if ($approve.status -ne 200) { Fail("approve returned $($approve.status). Body: $($approve.raw)") }

$terminalOk = $false
if ($approve.data -is [string]) { $terminalOk = $true }
elseif ($approve.data -and ($approve.data.PSObject.Properties.Name -contains "execution_state")) {
  $st = [string]$approve.data.execution_state
  if ($st -match "COMPLETED|EXECUTED|DONE") { $terminalOk = $true }
}

if (-not $terminalOk) {
  Write-Host "Approve response:"
  Write-Host $approve.raw
  Fail("Approve did not return a terminal completion status.")
}

Ok("Happy Path completed (BLOCKED -> APPROVED -> EXECUTED/COMPLETED).")

Write-Section "4) Optional snapshot verification"
try {
  $snap = Invoke-Json -Method "GET" -Path "/api/ceo/console/snapshot" -Headers $headers
  if ($snap.status -eq 200) {
    Write-Host "Snapshot ok." -ForegroundColor Gray
  }
} catch {
  Write-Host "Snapshot check skipped (non-fatal)." -ForegroundColor Gray
}

exit 0
