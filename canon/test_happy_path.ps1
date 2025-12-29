param(
  [Parameter(Mandatory=$false)]
  [string]$BaseUrl = "http://localhost:8000",

  # Ako imaš CEO_TOKEN_ENFORCEMENT=true, proslijedi token ovdje
  [Parameter(Mandatory=$false)]
  [string]$CeoToken = "",

  # Ako želiš koristiti /api/chat umjesto /api/ceo/command
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

  $h = @{}
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

function Get-ProposedCommandsFromResponse($data) {
  if ($null -eq $data) { return @() }

  # Standard: root.proposed_commands
  if ($data.PSObject.Properties.Name -contains "proposed_commands") {
    $pc = $data.proposed_commands
    if ($null -eq $pc) { return @() }
    return @($pc)
  }

  # Fallback: sometimes nested
  if ($data.PSObject.Properties.Name -contains "trace") {
    $t = $data.trace
    if ($t -and ($t.PSObject.Properties.Name -contains "proposed_commands")) {
      return @($t.proposed_commands)
    }
  }

  return @()
}

function Convert-ProposalToExecuteRawPayload($proposal) {
  if ($null -eq $proposal) { return $null }

  # 1) args.ai_command
  if ($proposal.PSObject.Properties.Name -contains "args") {
    $args = $proposal.args

    if ($args -and ($args.PSObject.Properties.Name -contains "ai_command")) {
      $ai = $args.ai_command
      if ($ai -and ($ai.PSObject.Properties.Name -contains "command") -and ($ai.PSObject.Properties.Name -contains "intent")) {
        return @{
          command   = [string]$ai.command
          intent    = [string]$ai.intent
          params    = $(if ($ai.PSObject.Properties.Name -contains "params") { $ai.params } else { @{} })
          initiator = "ceo"
          read_only = $false
          metadata  = @{
            canon  = "happy_path"
            source = "test_happy_path.ps1"
          }
        }
      }
    }

    # 2) args.command + args.intent
    if ($args -and ($args.PSObject.Properties.Name -contains "command") -and ($args.PSObject.Properties.Name -contains "intent")) {
      return @{
        command   = [string]$args.command
        intent    = [string]$args.intent
        params    = $(if ($args.PSObject.Properties.Name -contains "params") { $args.params } else { @{} })
        initiator = "ceo"
        read_only = $false
        metadata  = @{
          canon  = "happy_path"
          source = "test_happy_path.ps1"
        }
      }
    }
  }

  # 3) root.command (+ intent)
  if ($proposal.PSObject.Properties.Name -contains "command") {
    $cmd = [string]$proposal.command
    if ($cmd.Trim().Length -gt 0) {
      $intent = $cmd
      if ($proposal.PSObject.Properties.Name -contains "intent") {
        $intent = [string]$proposal.intent
        if ($intent.Trim().Length -eq 0) { $intent = $cmd }
      }

      $p = @{}
      if ($proposal.PSObject.Properties.Name -contains "params") { $p = $proposal.params }
      elseif ($proposal.PSObject.Properties.Name -contains "payload") { $p = $proposal.payload }

      return @{
        command   = $cmd
        intent    = $intent
        params    = $(if ($p) { $p } else { @{} })
        initiator = "ceo"
        read_only = $false
        metadata  = @{
          canon  = "happy_path"
          source = "test_happy_path.ps1"
        }
      }
    }
  }

  # 4) ceo_console_router shape: command_type + payload
  if (($proposal.PSObject.Properties.Name -contains "command_type") -and
      ($proposal.PSObject.Properties.Name -contains "payload")) {

    $ct = [string]$proposal.command_type
    if ($ct.Trim().Length -gt 0) {
      $p = $proposal.payload
      if ($null -eq $p) { $p = @{} }

      return @{
        command   = $ct
        intent    = $ct
        params    = $p
        initiator = "ceo"
        read_only = $false
        metadata  = @{
          canon  = "happy_path"
          source = "test_happy_path.ps1"
          proposal_shape = "command_type_payload"
        }
      }
    }
  }

  return $null
}

# -------------------------
# HEADERS (token if needed)
# -------------------------
$headers = @{}
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

# Prompt: explicit "propose only", do not execute
$prompt = "CANON HAPPY PATH (CEO Advisor): Propose a command to create a Notion task titled 'HP Test' with priority High and due tomorrow. DO NOT execute. Return proposed_commands."

function Invoke-ReadRequest {
  param([switch]$ViaChat)

  if ($ViaChat) {
    return Invoke-Json -Method "POST" -Path "/api/chat" -Body @{
      message = $prompt
      # extra hints (best-effort; backend may ignore)
      preferred_agent_id = "ceo_advisor"
      agent_id = "ceo_advisor"
      context = @{ preferred_agent_id = "ceo_advisor" }
    } -Headers $headers
  }

  # Send hints in multiple fields to match wrapper extractors:
  return Invoke-Json -Method "POST" -Path "/api/ceo/command" -Body @{
    text = $prompt
    initiator = "canon_test"
    session_id = $null

    # Root-level hints (some routers read these)
    preferred_agent_id = "ceo_advisor"
    agent_id = "ceo_advisor"

    # Wrapper reads these into context_hint/smart_context depending on implementation
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

# If user explicitly asked to use chat endpoint, do it
if ($UseChatEndpoint) {
  $readResp = Invoke-ReadRequest -ViaChat
} else {
  $readResp = Invoke-ReadRequest
}

if ($readResp.status -ne 200) { Fail("READ endpoint returned $($readResp.status)") }

$proposals = @(Get-ProposedCommandsFromResponse $readResp.data)

# If no proposals and we weren't using /api/chat, do an automatic fallback try via /api/chat
if ($proposals.Count -lt 1 -and -not $UseChatEndpoint) {
  Write-Host "No proposed_commands from /api/ceo/command. Retrying once via /api/chat..." -ForegroundColor Yellow
  $readResp2 = Invoke-ReadRequest -ViaChat
  if ($readResp2.status -eq 200) {
    $readResp = $readResp2
    $proposals = @(Get-ProposedCommandsFromResponse $readResp.data)
  }
}

if ($proposals.Count -lt 1) {
  Fail("No proposed_commands returned. Raw response: $($readResp.raw)")
}

Ok("proposed_commands present: $($proposals.Count)")
$proposal0 = $proposals[0]
Write-Host "Using proposal[0]..." -ForegroundColor Gray

Write-Section "2) Execute/raw (WRITE path creates approval)"
$execPayload = Convert-ProposalToExecuteRawPayload $proposal0
if ($null -eq $execPayload) {
  Fail("Cannot map proposal to execute/raw payload. Proposal[0]: $($proposal0 | ConvertTo-Json -Depth 30)")
}

$exec = Invoke-Json -Method "POST" -Path "/api/execute/raw" -Body $execPayload -Headers $headers
if ($exec.status -ne 200) { Fail("execute/raw returned $($exec.status). Body: $($exec.raw)") }

if (-not ($exec.data.PSObject.Properties.Name -contains "approval_id")) {
  Fail("execute/raw missing approval_id. Body: $($exec.raw)")
}
$approvalId = [string]$exec.data.approval_id
if ($approvalId.Trim().Length -eq 0) { Fail("approval_id empty. Body: $($exec.raw)") }
Ok("approval_id created: $approvalId")

Write-Section "3) Approve (governance gate resumes execution)"
$approve = Invoke-Json -Method "POST" -Path "/api/ai-ops/approval/approve" -Body @{ approval_id = $approvalId } -Headers $headers
if ($approve.status -ne 200) { Fail("approve returned $($approve.status). Body: $($approve.raw)") }

# terminal state check
$terminalOk = $false
if ($approve.data -is [string]) { $terminalOk = $true }
elseif ($approve.data -and ($approve.data.PSObject.Properties.Name -contains "execution_state")) {
  $st = [string]$approve.data.execution_state
  if ($st -match "COMPLETED|EXECUTED|DONE") { $terminalOk = $true }
}
elseif ($approve.data -and ($approve.data.PSObject.Properties.Name -contains "status")) {
  $st2 = [string]$approve.data.status
  if ($st2 -match "COMPLETED|EXECUTED|DONE|OK") { $terminalOk = $true }
}

if (-not $terminalOk) {
  Write-Host "Approve response:" -ForegroundColor Yellow
  Write-Host $approve.raw
  Fail("Approve did not return a terminal completion status.")
}

Ok("Happy Path completed (BLOCKED -> APPROVED -> EXECUTED/COMPLETED).")

Write-Section "4) Optional snapshot verification"
try {
  $snap = Invoke-Json -Method "GET" -Path "/api/ceo/console/snapshot" -Headers $headers
  if ($snap.status -eq 200) {
    $pending = $null
    if ($snap.data -and ($snap.data.PSObject.Properties.Name -contains "approvals")) {
      if ($snap.data.approvals.PSObject.Properties.Name -contains "pending_count") {
        $pending = $snap.data.approvals.pending_count
      }
    }
    Write-Host "Snapshot ok. approvals.pending_count=$pending" -ForegroundColor Gray
  }
} catch {
  Write-Host "Snapshot check skipped (non-fatal)." -ForegroundColor Gray
}

exit 0
