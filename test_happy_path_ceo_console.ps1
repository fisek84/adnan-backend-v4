# test_happy_path_ceo_console.ps1
Write-Host "HAPPY PATH (CEO Console SSOT) START" -ForegroundColor Cyan

$Base = "http://127.0.0.1:8000"

function PostJson($path, $obj) {
  return Invoke-RestMethod -Method Post -Uri ($Base + $path) -ContentType "application/json" -Body ($obj | ConvertTo-Json -Depth 80)
}

function Fail($msg) { Write-Host "FAIL: $msg" -ForegroundColor Red; exit 1 }
function Pass($msg) { Write-Host "PASS: $msg" -ForegroundColor Green }

function CoalesceString($v, $fallback) {
  if ($null -ne $v) {
    $s = [string]$v
    if ($s.Trim().Length -gt 0) { return $s }
  }
  return $fallback
}

# 1) CEO Console READ -> must return proposals (no approval_id/execution_id)
$prompt = "Notion ops: Kreiraj cilj 'HP TEST - Prodaja +20% u 60 dana' i poveži 2 taska. Izvrši nakon odobrenja."
$resp = PostJson "/api/ceo-console/command" @{ text = $prompt }

if (-not $resp) { Fail "ceo-console/command returned null" }
if (-not $resp.ok) { Fail "ceo-console/command not ok" }
if ($resp.PSObject.Properties.Name -contains "approval_id" -and $resp.approval_id) { Fail "READ response must NOT contain approval_id" }
if ($resp.PSObject.Properties.Name -contains "execution_id" -and $resp.execution_id) { Fail "READ response must NOT contain execution_id" }
Pass "READ response ok (no approval/execution ids)"

# 2) Must have at least one proposal
$pcs = @()
if ($resp.PSObject.Properties.Name -contains "proposed_commands") {
  $pcs = @($resp.proposed_commands)
}
if ($pcs.Count -lt 1) { Fail "proposed_commands missing/empty" }
Pass "proposed_commands present"

# 3) Pick first actionable proposal (prefer notion_write envelope, fallback ok)
$proposal = $null
$nw = $pcs | Where-Object { $_ -and ($_.command -eq "notion_write") -and ($_.requires_approval -eq $true) }
if ($nw -and $nw.Count -gt 0) { $proposal = $nw[0] } else { $proposal = $pcs[0] }

if (-not $proposal) { Fail "No proposal selected" }
$cmd = CoalesceString $proposal.command "unknown"
Pass ("Selected proposal: " + $cmd)

# 4) Execute RAW -> must return approval_id + execution_id
$exec = PostJson "/api/execute/raw" $proposal
if (-not $exec) { Fail "execute/raw returned null" }

$approvalId  = ""
$executionId = ""

if ($exec.PSObject.Properties.Name -contains "approval_id")  { $approvalId  = CoalesceString $exec.approval_id "" }
if ($exec.PSObject.Properties.Name -contains "execution_id") { $executionId = CoalesceString $exec.execution_id "" }

if (-not $approvalId.Trim())  { Fail "execute/raw missing approval_id" }
if (-not $executionId.Trim()) { Fail "execute/raw missing execution_id" }
Pass "execute/raw returned approval_id + execution_id"

# 5) Approve -> must not stay BLOCKED
$appr = PostJson "/api/ai-ops/approval/approve" @{ approval_id = $approvalId }
if (-not $appr) { Fail "approval/approve returned null" }

$state = ""
if ($appr.PSObject.Properties.Name -contains "execution_state") { $state = CoalesceString $appr.execution_state "" }
elseif ($appr.PSObject.Properties.Name -contains "state") { $state = CoalesceString $appr.state "" }
elseif ($appr.PSObject.Properties.Name -contains "status") { $state = CoalesceString $appr.status "" }

if ($state -and $state.ToUpper().Contains("BLOCK")) { Fail ("Still BLOCKED after approve: " + $state) }

if ($state) { Pass ("approve ok (state=" + $state + ")") } else { Pass "approve ok" }

Write-Host "HAPPY PATH (CEO Console SSOT) PASSED" -ForegroundColor Cyan
