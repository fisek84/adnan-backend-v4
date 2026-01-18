param(
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [string]$SessionId = "phase5-test-1"
)

function J($o){ $o | ConvertTo-Json -Depth 20 }
function PostJson($url,$obj){
  try {
    return Invoke-RestMethod -Method Post -Uri $url -ContentType "application/json" -Body (J $obj)
  } catch {
    $resp = $_.Exception.Response
    if($resp -and $resp.GetResponseStream()){
      $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
      $body = $sr.ReadToEnd()
      throw "HTTP ERROR on $url`n$body"
    }
    throw
  }
}
function GetText($url){
  try { return (Invoke-WebRequest -UseBasicParsing $url).Content } catch { throw }
}

Write-Host "== PHASE 5: Happy Path (single create task) =="

# 0) Health
$health = GetText "$BaseUrl/health"
Write-Host "[health] $health"

# 1) Ask CEO console for proposal (READ-only)
$prompt = "kreiraj task u notionu: Phase5 Test " + (Get-Date -Format "yyyyMMdd-HHmmss")
$ceoReq = @{ input_text=$prompt; session_id=$SessionId; source="ceo_dashboard" }
$ceo = PostJson "$BaseUrl/api/ceo-console/command" $ceoReq
Write-Host "[ceo-console] ok=$($ceo.ok) read_only=$($ceo.read_only)"
if(-not $ceo.proposed_commands -or $ceo.proposed_commands.Count -lt 1){ throw "No proposed_commands returned." }

$pc = $ceo.proposed_commands[0]
Write-Host "[proposal] command=$($pc.command) intent=$($pc.intent)"

# 2) Create approval via /api/execute/raw (BLOCKED expected)
# Canon payload for unwrap expects params.prompt OR metadata.wrapper.prompt.
$rawBody = @{
  command = "ceo.command.propose"
  intent  = "ceo.command.propose"
  params  = @{ prompt = $prompt }
  metadata = @{
    wrapper = @{ prompt = $prompt }
    session_id = $SessionId
    source = "ceo_console"
  }
}
$raw = PostJson "$BaseUrl/api/execute/raw" $rawBody
Write-Host "[execute/raw] status=$($raw.status) execution_state=$($raw.execution_state) approval_id=$($raw.approval_id) execution_id=$($raw.execution_id)"
if($raw.execution_state -ne "BLOCKED"){ throw "Expected BLOCKED from /api/execute/raw, got: $($raw.execution_state)" }

# 3) Approve + execute
$approveBody = @{ approval_id = $raw.approval_id }
$appr = PostJson "$BaseUrl/api/ai-ops/approval/approve" $approveBody
Write-Host "[approve] execution_state=$($appr.execution_state)"

# 4) Print result URL if present
try {
  $url = $appr.result.result.url
  if($url){ Write-Host "[RESULT URL] $url" } else { Write-Host "[RESULT URL] (not found in response shape)" }
} catch {
  Write-Host "[RESULT URL] (could not read nested url field)"
}

Write-Host "== DONE =="
