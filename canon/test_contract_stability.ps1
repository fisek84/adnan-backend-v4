Param([string]$BaseUrl="http://127.0.0.1:8000")
$ErrorActionPreference="Stop"

Write-Host "=== CONTRACT STABILITY TEST START ==="

# 1) /api/chat -> args.prompt exists, params absent
$body = @{ message = "create goal Contract Stability Check" } | ConvertTo-Json
$r = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/chat" -ContentType "application/json" -Body $body

if (-not $r.proposed_commands[0].args.prompt) { throw "CHAT CONTRACT BROKEN: missing proposed_commands[0].args.prompt" }
if ($r.proposed_commands[0].params) { throw "CHAT CONTRACT BROKEN: params present (should not be on /api/chat)" }
Write-Host "PASS: /api/chat contract ok"

# 2) /api/execute/raw -> accepts wrapper with params.prompt
$exec = @{
  initiator="ceo"
  read_only=$false
  metadata=@{ canon="contract"; source="test_contract_stability.ps1" }
  command="ceo.command.propose"
  intent="ceo.command.propose"
  params=@{ prompt="create goal Contract Stability Check" }
} | ConvertTo-Json -Depth 20

$raw = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/execute/raw" -ContentType "application/json" -Body $exec
if ($raw.execution_state -ne "BLOCKED") { throw "EXECUTE/RAW BROKEN: expected BLOCKED" }
if (-not $raw.approval_id) { throw "EXECUTE/RAW BROKEN: missing approval_id" }
Write-Host "PASS: /api/execute/raw promotion ok"

Write-Host "=== CONTRACT STABILITY TEST PASSED ==="
