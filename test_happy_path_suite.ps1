# C:\adnan-backend-v4\test_happy_path_goal_and_task.ps1
Write-Host "=== GOAL + TASK HAPPY PATH START ==="

$BASE = "http://127.0.0.1:8000"

# 1) Create via NL -> expect BLOCKED + approval_id
$r = Invoke-RestMethod `
  -Method POST `
  -Uri "$BASE/api/execute" `
  -ContentType "application/json" `
  -Body '{
    "text": "create goal Test Goal+Task Happy Path with task"
  }'

if ($r.execution_state -ne "BLOCKED") {
  throw "EXPECTED BLOCKED, got: $($r.execution_state)"
}

if (-not $r.approval_id) {
  throw "approval_id missing"
}

$approval = $r.approval_id
Write-Host "BLOCKED with approval_id=$approval"

# 2) Approval must exist (LIST-based)
$pending = Invoke-RestMethod `
  -Method GET `
  -Uri "$BASE/api/ai-ops/approval/pending"

$approvalIds = $pending.approvals | ForEach-Object { $_.approval_id }

if (-not ($approvalIds -contains $approval)) {
  throw "approval not found in pending list"
}

Write-Host "Approval is pending"

# 3) Approve (new contract: validate approval status, not execution_state)
$approved = Invoke-RestMethod `
  -Method POST `
  -Uri "$BASE/api/ai-ops/approval/approve" `
  -ContentType "application/json" `
  -Body (@{ approval_id = $approval } | ConvertTo-Json)

# approve endpoint may return either:
# A) { status: "approved", ... }  (approval record)
# B) { ok: true, approval: {...status:"approved"...}, ... } (wrapped)
$status = $approved.status
if (-not $status -and $approved.approval) { $status = $approved.approval.status }

if ($status -ne "approved") {
  throw "EXPECTED approval status=approved, got: $status"
}

Write-Host "Approval approved"
Write-Host "=== GOAL + TASK HAPPY PATH PASSED (approval lifecycle) ==="
