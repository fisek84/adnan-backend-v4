Param(
    [string]$BaseUrl = "http://localhost:8000"
)

Write-Host "=== RUNNING HAPPY PATH TEST SUITE ==="
Write-Host "BaseUrl = $BaseUrl"
Write-Host ""

$tests = @(
    "test_happy_path.ps1",
    "test_happy_path_goal_and_task.ps1",
    "test_happy_path_ceo_goal_plan_7day.ps1",
    "test_happy_path_ceo_goal_plan_14day.ps1",
    "test_happy_path_kpi_weekly_summary.ps1"
)

foreach ($t in $tests) {
    Write-Host ">>> Running $t ..."
    & ".\${t}" -BaseUrl $BaseUrl
    Write-Host ">>> $t PASSED"
    Write-Host ""
}

Write-Host "ALL HAPPY PATH TESTS PASSED"
