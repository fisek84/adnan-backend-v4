Param(
  [string]$BaseUrl = "http://127.0.0.1:8000"
)

Write-Host "HAPPY PATH (CEO COMMAND->PROPOSAL->APPROVAL->EXECUTE) START"
Write-Host "BaseUrl = $BaseUrl"
Write-Host ""

# 0) baseline pending count
$pending0 = (Invoke-RestMethod -Method GET "$BaseUrl/api/ai-ops/approval/pending").approvals.Count

# 1) /api/ceo/command -> MORA vratiti proposal deterministiÄŤki
$rawChat = (Invoke-WebRequest -UseBasicParsing -Method POST "$BaseUrl/api/ceo/command" `
  -ContentType "application/json" `
  -Body (@{
    message = "create goal Test Happy Path from Chat"
  } | ConvertTo-Json -Depth 5)
).Content

$dataChat = $rawChat | ConvertFrom-Json

if ($null -eq $dataChat.proposed_commands -or $dataChat.proposed_commands.Count -lt 1) {
  throw "FAILED: ceo.command proposed_commands empty. Raw=$rawChat"
}

$pc = $dataChat.proposed_commands[0]

if ($pc.command -ne "ceo.command.propose") {
  throw "FAILED: expected ceo.command.propose, got: $($pc.command). Raw=$rawChat"
}

if (-not $pc.args -or -not $pc.args.prompt) {
  throw "FAILED: proposal missing args.prompt. Raw=$rawChat"
}

# =========================================================
# 3ď¸ŹâŁ TEST: Confidence & Risk Scoring (KANON)
# =========================================================
if (-not $pc.payload_summary) {
  throw "FAILED: payload_summary missing on proposal"
}

if ($null -eq $pc.payload_summary.confidence_score) {
  throw "FAILED: confidence_score missing"
}

if ($pc.payload_summary.confidence_score -lt 0.0 -or $pc.payload_summary.confidence_score -gt 1.0) {
  throw "FAILED: confidence_score out of range (0.0-1.0)"
}

if ($pc.risk -notin @("LOW","MED","HIGH")) {
  throw "FAILED: invalid risk level"
}

if ($null -eq $pc.payload_summary.assumption_count -or $pc.payload_summary.assumption_count -lt 0) {
  throw "FAILED: assumption_count invalid"
}

# =========================================================
# 4ď¸ŹâŁ TEST: Recommendation Typing (KANON)
# =========================================================
if (-not $pc.payload_summary.recommendation_type) {
  throw "FAILED: recommendation_type missing"
}

if ($pc.payload_summary.recommendation_type -notin @(
  "STRATEGIC",
  "OPERATIONAL",
  "DEFENSIVE",
  "EXPERIMENTAL",
  "INFORMATIONAL"
)) {
  throw "FAILED: invalid recommendation_type"
}

# ceo.command ne smije kreirati approvals direktno
$pending1 = (Invoke-RestMethod -Method GET "$BaseUrl/api/ai-ops/approval/pending").approvals.Count
if ($pending1 -ne $pending0) {
  throw "FAILED: pending approvals changed ($pending0 -> $pending1)"
}

Write-Host "OK: proposal captured; pending unchanged ($pending0 -> $pending1)"
Write-Host "proposal.command=$($pc.command)"
Write-Host "proposal.prompt=$($pc.args.prompt)"
Write-Host ""

# 2) PROMOTE -> mora vratiti BLOCKED + approval_id (+ execution_id)
$bodyPromote = @{
  initiator = "ceo"
  proposal  = $pc
} | ConvertTo-Json -Depth 30

$rawPromote = (Invoke-WebRequest -UseBasicParsing -Method POST `
  "$BaseUrl/api/proposals/execute" `
  -ContentType "application/json" `
  -Body $bodyPromote
).Content

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

  # 4) APPROVE -> mora zavrĹˇiti COMPLETED
  $rawApprove = (Invoke-WebRequest -UseBasicParsing -Method POST `
    "$BaseUrl/api/ai-ops/approval/approve" `
    -ContentType "application/json" `
    -Body (@{
      approval_id = $approvalId
    } | ConvertTo-Json)
  ).Content

  $dataApprove = $rawApprove | ConvertFrom-Json

  if ($dataApprove.execution_state -ne "COMPLETED") {
    throw "FAILED: expected COMPLETED after approve. Raw=$rawApprove"
  }

  Write-Host "PASSED: approve -> COMPLETED"
  Write-Host "HAPPY PATH PASSED"
}
finally {
  if ($approvalId) {
    try {
      $null = (Invoke-WebRequest -UseBasicParsing -Method POST `
        "$BaseUrl/api/ai-ops/approval/reject" `
        -ContentType "application/json" `
        -Body (@{
          approval_id = $approvalId
          reason      = "test_cleanup"
        } | ConvertTo-Json)
      ).Content
    } catch { }
  }
}
