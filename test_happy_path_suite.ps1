Param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

Write-Host "=== RUNNING HAPPY PATH TEST SUITE ==="
Write-Host "BaseUrl = $BaseUrl"
Write-Host ""

$tests = @(
    "test_happy_path.ps1",
    "test_happy_path_goal_and_task.ps1",
    "test_happy_path_ceo_goal_plan_7day.ps1",
    "test_happy_path_ceo_goal_plan_14day.ps1",
    "test_happy_path_kpi_weekly_summary.ps1",
    "test_happy_path_chat_proposal.ps1"
)

foreach ($t in $tests) {
    if (-not (Test-Path ".\${t}")) {
        throw "Missing test file: $t"
    }

    Write-Host ">>> Running $t ..."
    & ".\${t}" -BaseUrl $BaseUrl
    if ($LASTEXITCODE -ne 0) {
        throw "$t FAILED (exit code=$LASTEXITCODE)"
    }

    Write-Host ">>> $t PASSED"
    Write-Host ""
}

Write-Host "ALL HAPPY PATH TESTS PASSED"
