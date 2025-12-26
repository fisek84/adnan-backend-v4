Param(
  [string]$BaseUrl = "http://127.0.0.1:8000"
)

Write-Host "HAPPY PATH (CHAT->PROPOSAL->APPROVAL->EXECUTE) START"
Write-Host "BaseUrl = $BaseUrl"
Write-Host ""

# 0) baseline pending count (chat ne smije mijenjati)
$pending0 = (Invoke-RestMethod -Method GET "$BaseUrl/api/ai-ops/approval/pending").approvals.Count

# 1) /api/chat (READ-only) -> mora vratiti proposal
$rawChat = (Invoke-WebRequest -UseBasicParsing -Method POST "$BaseUrl/api/chat" -ContentType "application/json" -Body (@{
  message = "create goal Test Happy Path from Chat"
} | ConvertTo-Json)).Content

$dataChat = $rawChat | ConvertFrom-Json

if ($null -eq $dataChat.proposed_commands -or $dataChat.proposed_commands.Count -lt 1) {
  throw "FAILED: chat proposed_commands empty. Raw=$rawChat"
}

$pc = $dataChat.proposed_commands[0]

if ($pc.command -ne "ceo.command.propose") {
  throw "FAILED: expected ceo.command.propose, got: $($pc.command). Raw=$rawChat"
}

if (-not $pc.args -or -not $pc.args.prompt) {
  throw "FAILED: proposal missing args.prompt. Raw=$rawChat"
}

# chat ne smije kreirati approvals
$pending1 = (Invoke-RestMethod -Method GET "$BaseUrl/api/ai-ops/approval/pending").approvals.Count
if ($pending1 -ne $pending0) {
  throw "FAILED: pending approvals changed ($pending0 -> $pending1) during chat"
}

Write-Host "OK: chat proposal captured; pending unchanged ($pending0 -> $pending1)"
Write-Host "proposal.command=$($pc.command)"
Write-Host "proposal.prompt=$($pc.args.prompt)"
Write-Host ""

# 2) PROMOTE -> mora vratiti BLOCKED + approval_id (+ execution_id)
$bodyPromote = @{
  initiator = "ceo"
  proposal  = $pc
} | ConvertTo-Json -Depth 30

$rawPromote = (Invoke-WebRequest -UseBasicParsing -Method POST "$BaseUrl/api/proposals/execute" -ContentType "application/json" -Body $bodyPromote).Content
$dataPromote = $rawPromote | ConvertFrom-Json

if ($dataPromote.execution_state -ne "BLOCKED" -and $dataPromote.status -ne "BLOCKED") {
  throw "FAILED: expected BLOCKED from promote. Raw=$rawPromote"
}

$approvalId = $dataPromote.approval_id
if (-not $approvalId) { throw "FAILED: promote missing approval_id. Raw=$rawPromote" }

$executionId = $dataPromote.execution_id
if (-not $executionId) { throw "FAILED: promote missing execution_id. Raw=$rawPromote" }

Write-Host "OK: promoted BLOCKED approval_id=$approvalId execution_id=$executionId"
Write-Host ""

try {
  # 3) Approval mora biti u pending listi
  $pendingList = Invoke-RestMethod -Method GET "$BaseUrl/api/ai-ops/approval/pending"
  $ids = @($pendingList.approvals | ForEach-Object { $_.approval_id })

  if (-not ($ids -contains $approvalId)) {
    throw "FAILED: approval_id not found in pending list: $approvalId"
  }

  Write-Host "OK: approval is pending"
  Write-Host ""

  # 4) APPROVE -> mora završiti COMPLETED
  $rawApprove = (Invoke-WebRequest -UseBasicParsing -Method POST "$BaseUrl/api/ai-ops/approval/approve" -ContentType "application/json" -Body (@{
    approval_id = $approvalId
  } | ConvertTo-Json)).Content

  $dataApprove = $rawApprove | ConvertFrom-Json

  if ($dataApprove.execution_state -ne "COMPLETED") {
    throw "FAILED: expected COMPLETED after approve. Raw=$rawApprove"
  }

  Write-Host "PASSED: approve -> COMPLETED"
  Write-Host "HAPPY PATH (CHAT->PROPOSAL->APPROVAL->EXECUTE) PASSED"
}
finally {
  # Best-effort cleanup ako test pukne prije approve; ako nema reject endpoint, ignore.
  if ($approvalId) {
    try {
      $null = (Invoke-WebRequest -UseBasicParsing -Method POST "$BaseUrl/api/ai-ops/approval/reject" -ContentType "application/json" -Body (@{
        approval_id = $approvalId
        reason = "test_cleanup"
      } | ConvertTo-Json)).Content
    } catch { }
  }
}
