# test_notion_happy_path_write.ps1
# CANON (2026-01): /api/chat is READ/PROPOSE ONLY, and proposed_commands MUST be sent 1:1 (opaque) to /api/execute/raw.
# This test:
#  1) calls /api/chat with metadata.require_approval=true and a write prompt
#  2) takes proposed_commands[0] EXACTLY as returned and POSTs it to /api/execute/raw
#  3) if BLOCKED -> approves via /api/ai-ops/approval/approve
#  4) asserts Notion write evidence exists (page_id + url) in final result

param(
  [Parameter(Mandatory=$false)]
  [string]$BaseUrl = "http://localhost:8000",

  [Parameter(Mandatory=$false)]
  [string]$CeoToken = "",

  [Parameter(Mandatory=$false)]
  [ValidateSet("goals","tasks")]
  [string]$DbKey = "goals"
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
    $jsonBody = ($Body | ConvertTo-Json -Depth 50)
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

function Dump-Json([string]$label, $obj) {
  Write-Host ("--- {0} ---" -f $label)
  try { Write-Host ($obj | ConvertTo-Json -Depth 80) } catch { Write-Host ($obj | Out-String) }
  Write-Host ("--- END {0} ---" -f $label)
}

function Approve-IfBlocked($resp) {
  if ($null -eq $resp) { Fail("Approve-IfBlocked received null response") }

  if (($resp.PSObject.Properties.Name -contains "execution_state") -and ([string]$resp.execution_state -eq "BLOCKED")) {
    if (-not ($resp.PSObject.Properties.Name -contains "approval_id")) {
      Dump-Json "BLOCKED RESPONSE (missing approval_id)" $resp
      Fail("execution_state=BLOCKED but approval_id missing")
    }

    $approvalId = [string]$resp.approval_id
    if ($approvalId.Trim().Length -eq 0) {
      Dump-Json "BLOCKED RESPONSE (empty approval_id)" $resp
      Fail("execution_state=BLOCKED but approval_id empty")
    }

    Write-Host "Approving approval_id=$approvalId ..."
    $approved = Invoke-Json -Method "POST" -Path "/api/ai-ops/approval/approve" -Body @{ approval_id = $approvalId } -Headers $headers
    if ($approved.status -ne 200) {
      Fail("approve returned HTTP $($approved.status). Body: $($approved.raw)")
    }
    return $approved.data
  }

  return $resp
}

function Get-ProposedCommandsFromChat($chatData) {
  if ($null -eq $chatData) { return @() }

  if ($chatData.PSObject.Properties.Name -contains "proposed_commands") {
    if ($chatData.proposed_commands -is [System.Collections.IEnumerable] -and -not ($chatData.proposed_commands -is [string])) {
      return @($chatData.proposed_commands)
    }
    return @($chatData.proposed_commands)
  }

  return @()
}

function Execute-Raw-Opaque($proposalObj) {
  if ($null -eq $proposalObj) { Fail("Execute-Raw-Opaque received null proposal") }

  # CANON: send EXACT object as returned (opaque). Do NOT re-map/rebuild.
  $exec = Invoke-Json -Method "POST" -Path "/api/execute/raw" -Body $proposalObj -Headers $headers
  if ($exec.status -ne 200) { Fail("execute/raw returned HTTP $($exec.status). Body: $($exec.raw)") }

  $out = $exec.data
  $out = Approve-IfBlocked $out
  return $out
}

function Find-NotionEvidence($resp) {
  # Expected shape (based on your real working response):
  # resp.result.result.page_id / resp.result.result.url
  if ($null -eq $resp) { return $null }

  $r0 = $null
  if ($resp.PSObject.Properties.Name -contains "result") { $r0 = $resp.result }

  $r1 = $null
  if ($r0 -and ($r0.PSObject.Properties.Name -contains "result")) { $r1 = $r0.result }

  # fallback: sometimes services may put it at resp.result directly
  if (-not $r1) { $r1 = $r0 }

  if (-not $r1) { return $null }

  $pageId = $null
  $url = $null

  if ($r1.PSObject.Properties.Name -contains "page_id") { $pageId = $r1.page_id }
  if ($r1.PSObject.Properties.Name -contains "url") { $url = $r1.url }

  if (($null -ne $pageId) -and ([string]$pageId).Trim().Length -gt 0 -and
      ($null -ne $url) -and ([string]$url).Trim().Length -gt 0) {
    return [PSCustomObject]@{ page_id = [string]$pageId; url = [string]$url; intent = ($r1.intent) }
  }

  return $null
}

# -----------------------------
# HEADERS
# -----------------------------
$headers = @{}
if ($CeoToken.Trim().Length -gt 0) {
  $headers["X-CEO-Token"] = $CeoToken.Trim()
}

Write-Host "=== NOTION HAPPY PATH WRITE TEST (CANON: OPAQUE proposals) START ==="

Write-Section "0) Health check"
$health = Invoke-Json -Method "GET" -Path "/health" -Headers $headers
if ($health.status -ne 200) { Fail("health returned HTTP $($health.status)") }
Ok("health ok")

# Unique title
$ts = (Get-Date).ToString("yyyyMMdd_HHmmss")
$title = "HP Test $DbKey $ts"

Write-Section "1) /api/chat -> proposed_commands (READ/PROPOSE ONLY)"
# CANON: require_approval is read from payload.metadata.require_approval in chat_router
$prompt =
  if ($DbKey -eq "goals") {
    "Kreiraj cilj `"$title`" status Aktivan priority Visok. Vrati proposed_commands."
  } else {
    "Kreiraj task `"$title`" priority High due tomorrow. Vrati proposed_commands."
  }

$chatBody = @{
  message = $prompt
  preferred_agent_id = "ceo_advisor"
  metadata = @{
    require_approval = $true
    source = "test_notion_happy_path_write.ps1"
  }
}

$chat = Invoke-Json -Method "POST" -Path "/api/chat" -Body $chatBody -Headers $headers
if ($chat.status -ne 200) { Fail("/api/chat returned HTTP $($chat.status). Body: $($chat.raw)") }

$pcs = @(Get-ProposedCommandsFromChat $chat.data)
if ($pcs.Count -lt 1) {
  Dump-Json "CHAT RESPONSE (no proposed_commands)" $chat.data
  Fail("No proposed_commands returned from /api/chat (expected at least 1).")
}
Ok("proposed_commands present: $($pcs.Count)")

$proposal0 = $pcs[0]
if (-not ($proposal0.PSObject.Properties.Name -contains "command")) {
  Dump-Json "PROPOSAL[0] (missing command)" $proposal0
  Fail("Proposal[0] missing 'command'")
}

Write-Section "2) /api/execute/raw (OPAQUE) -> approve if BLOCKED"
$execOut = Execute-Raw-Opaque $proposal0

if (-not ($execOut.PSObject.Properties.Name -contains "execution_state")) {
  Dump-Json "EXECUTE/RAW RESPONSE (missing execution_state)" $execOut
  Fail("execute/raw response missing execution_state")
}

$st = [string]$execOut.execution_state
if ($st -ne "COMPLETED") {
  Dump-Json "EXECUTE/RAW RESPONSE (NOT COMPLETED)" $execOut
  Fail("Expected execution_state=COMPLETED, got: $st")
}
Ok("execute/raw completed")

Write-Section "3) Assert Notion write evidence exists"
$evidence = Find-NotionEvidence $execOut
if (-not $evidence) {
  Dump-Json "EXECUTE/RAW RESPONSE (missing Notion evidence)" $execOut
  Fail("Missing Notion evidence (page_id/url) in response.result.result (or equivalent).")
}

Write-Host ("Notion create evidence: page_id={0}, url={1}" -f $evidence.page_id, $evidence.url)
Ok("Notion evidence present")

Write-Host "=== NOTION HAPPY PATH WRITE TEST (CANON) PASSED ===" -ForegroundColor Green
exit 0
