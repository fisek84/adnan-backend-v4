# canon\test_decision_outcome_registry_single.ps1
$ErrorActionPreference = "Stop"
$Base = "http://localhost:8000"

Write-Host "=== DECISION OUTCOME REGISTRY SINGLE-RECORD CANON TEST START ==="

# 0) Clean disk state
Remove-Item ".\.data\decision_outcomes.json" -ErrorAction SilentlyContinue

# 1) Create approval via execute/raw (BLOCKED)
$body = @{
  command   = "create_page"
  intent    = "create_page"
  initiator = "ceo"
  read_only = $false
  metadata  = @{}
  params    = @{
    db_key = "tasks"
    property_specs = @{
      Name = @{ type = "title"; value = "DOR Single Record Test" }
    }
  }
}

$r1 = Invoke-RestMethod -Method Post -Uri "$Base/api/execute/raw" -ContentType "application/json" -Body ($body | ConvertTo-Json -Depth 20)
if ($r1.status -ne "BLOCKED" -or -not $r1.approval_id) { throw "Expected BLOCKED with approval_id" }

# 2) Approve (executes once)
$approve = @{ approval_id = $r1.approval_id; approved_by = "ceo" }
$r2 = Invoke-RestMethod -Method Post -Uri "$Base/api/ai-ops/approval/approve" -ContentType "application/json" -Body ($approve | ConvertTo-Json -Compress)
if ($r2.execution_state -ne "COMPLETED") { throw "Expected COMPLETED, got $($r2.execution_state)" }

# 3) Assert registry file exists and has exactly 1 record
python -c "import json, pathlib; p=pathlib.Path('.data/decision_outcomes.json'); assert p.exists(), 'missing decision_outcomes.json'; d=json.loads(p.read_text('utf-8')); store=d.get('store') or {}; assert isinstance(store, dict); assert len(store)==1, f'expected 1 record, got {len(store)}'; print('PASS: records=1')"

Write-Host "=== DECISION OUTCOME REGISTRY SINGLE-RECORD CANON TEST PASSED ==="
