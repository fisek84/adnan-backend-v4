# tests/test_notion_ops_armed_gate.ps1
# PHASE 6: Notion Ops ARMED Gate
# E2E smoke test for /api/chat gating behavior.

$ErrorActionPreference = "Stop"

function Assert-True($cond, $msg) {
  if (-not $cond) { throw "ASSERT FAILED: $msg" }
}

function Assert-Eq($a, $b, $msg) {
  if ($a -ne $b) { throw "ASSERT FAILED: $msg (got='$a', expected='$b')" }
}

function Post-Json($url, $obj, $timeoutSec = 120) {
  $body = ($obj | ConvertTo-Json -Depth 30)
  Write-Host "POST $url (timeout=${timeoutSec}s)"
  # NOTE: TimeoutSec is critical; without it, a slow LLM call can hang the test indefinitely.
  return Invoke-RestMethod -Method Post -Uri $url -ContentType "application/json" -Body $body -TimeoutSec $timeoutSec
}

function Dump-Json($label, $obj) {
  Write-Host "---- $label ----"
  try { ($obj | ConvertTo-Json -Depth 30) | Write-Host } catch { Write-Host ($obj | Out-String) }
  Write-Host "----------------"
}

# --- Config ---
$BaseUrl = "http://127.0.0.1:8000"
$ChatUrl = "$BaseUrl/api/chat"

# Stable per-session key (must persist across requests)
$SessionId = "test_notion_ops_gate_session_001"

Write-Host "PHASE6: Using ChatUrl=$ChatUrl SessionId=$SessionId"

# ------------------------------------------------------------
# Test 1: NOT ARMED -> write intent prompt must NOT emit executable proposals
# ------------------------------------------------------------
Write-Host "`n[Test 1] Not armed -> write intent is blocked (NO executable proposals)."
$r1 = Post-Json $ChatUrl @{
  message   = "Kreiraj task u Notionu: Name: Test Task; Priority: High"
  metadata  = @{ session_id = $SessionId; initiator = "ps_test" }
} 180
Dump-Json "RESP1" $r1

$pcs1 = @()
if ($null -ne $r1.proposed_commands) { $pcs1 = @($r1.proposed_commands) }

if ($pcs1.Count -gt 0) {
  $pc = $pcs1[0]

  # Not armed: MUST NOT emit executable approval-flow proposal
  Assert-Eq $pc.scope "none" "Not armed must return non-executable proposal (scope=none)."
  Assert-Eq $pc.requires_approval $false "Not armed must not require approval."

  # Not armed: MUST NOT emit notion_write envelope
  Assert-True ($pc.command -ne "notion_write") "Not armed must not return notion_write proposal."
}

Assert-True (($r1.text -as [string]).ToLower().Contains("notion ops")) "Response should mention Notion Ops activation hint."

# ------------------------------------------------------------
# Test 2: Activate -> backend stores ARMED state (per-session)
# ------------------------------------------------------------
Write-Host "`n[Test 2] Activate -> NOTION OPS becomes ARMED."
$r2 = Post-Json $ChatUrl @{
  message  = "notion ops aktiviraj"
  metadata = @{ session_id = $SessionId; initiator = "ps_test" }
} 60
Dump-Json "RESP2" $r2

Assert-True ($null -ne $r2.notion_ops) "Activate response should include notion_ops state."
Assert-Eq $r2.notion_ops.armed $true "Notion Ops should be armed after activation."
Assert-True ([string]$r2.text -match "ARMED") "Activate response text should confirm ARMED."

# ------------------------------------------------------------
# Test 3: ARMED -> write intent may emit approval flow proposals
# ------------------------------------------------------------
Write-Host "`n[Test 3] Armed -> write intent yields approval-flow proposal (requires_approval=true, scope=api_execute_raw)."
$r3 = Post-Json $ChatUrl @{
  message  = "Kreiraj task u Notionu: Name: Test Task 2; Priority: Medium"
  metadata = @{ session_id = $SessionId; initiator = "ps_test" }
} 180
Dump-Json "RESP3" $r3

$pcs3 = @()
if ($null -ne $r3.proposed_commands) { $pcs3 = @($r3.proposed_commands) }
Assert-True ($pcs3.Count -ge 1) "Armed write intent should return at least 1 proposed_command."

$pc3 = $pcs3[0]
Assert-Eq $pc3.dry_run $true "Armed proposals must be dry_run=true (chat is read-only)."
Assert-Eq $pc3.requires_approval $true "Armed proposals must require approval."
Assert-Eq $pc3.scope "api_execute_raw" "Armed proposals must be scoped to api_execute_raw."

# ------------------------------------------------------------
# Test 4: Deactivate -> DISARM and block again
# ------------------------------------------------------------
Write-Host "`n[Test 4] Deactivate -> Notion Ops becomes DISARMED."
$r4 = Post-Json $ChatUrl @{
  message  = "notion ops ugasi"
  metadata = @{ session_id = $SessionId; initiator = "ps_test" }
} 60
Dump-Json "RESP4" $r4

Assert-True ($null -ne $r4.notion_ops) "Deactivate response should include notion_ops state."
Assert-Eq $r4.notion_ops.armed $false "Notion Ops should be disarmed after deactivation."
Assert-True ([string]$r4.text -match "DISARMED") "Deactivate response text should confirm DISARMED."

Write-Host "`nALL TESTS PASSED: test_notion_ops_armed_gate.ps1"
