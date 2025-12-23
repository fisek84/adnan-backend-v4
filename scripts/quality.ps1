param(
    [switch]$Fix
)

# Minimalni code-quality gate za Adnan.AI backend
# KANON-FIX-008_CODE_QUALITY_LAYER
# - Ruff lint (ruff check)
# - Ruff format (ruff format / --check)
# - Mypy za orchestrator + queue + dependencies wiring
# Skripta NE mijenja business logiku, samo provjerava kvalitet.

$ErrorActionPreference = "Stop"

# Repo root je parent folder od scripts/
$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== Adnan.AI :: Code Quality Layer (KANON-FIX-008) ==="
Write-Host "Repo root: $repoRoot"
Write-Host ""

Push-Location $repoRoot

try {
    # 1) Ruff lint (check)
    Write-Host "==> [1/3] Ruff lint: python -m ruff check ."
    python -m ruff check .
    Write-Host "    Ruff lint PASSED."
    Write-Host ""

    # 2) Ruff format (format ili --check, ovisno o -Fix)
    if ($Fix.IsPresent) {
        Write-Host "==> [2/3] Ruff format (auto-fix): python -m ruff format ."
        python -m ruff format .
        Write-Host "    Ruff format (auto-fix) DONE."
    }
    else {
        Write-Host "==> [2/3] Ruff format check: python -m ruff format --check ."
        python -m ruff format --check .
        Write-Host "    Ruff format check PASSED."
    }
    Write-Host ""

    # 3) Mypy za minimalni scope (orchestrator + queue + dependencies wiring)
    Write-Host "==> [3/3] mypy: python -m mypy services/orchestrator services/queue dependencies.py"
    python -m mypy services/orchestrator services/queue dependencies.py
    Write-Host "    mypy PASSED."
    Write-Host ""

    Write-Host "=== QUALITY SUCCESS (KANON-FIX-008) ==="
    exit 0
}
catch {
    Write-Host ""
    Write-Error "=== QUALITY FAILED (KANON-FIX-008) ==="
    Write-Error $_
    exit 1
}
finally {
    Pop-Location
}
