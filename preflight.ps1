$ErrorActionPreference = "Stop"
$global:LASTEXITCODE = 0

try {
    # --- 0) Local Docker DB target (single source of truth) ---
    # We use the stable local Postgres container name.
    $DB_CONTAINER = "adnan-pg"
    $DB_USER = "admin"
    $DB_NAME = "alignment_db"

    # Ensure DB container is running
    $running = docker ps --format "{{.Names}}" | Select-String -SimpleMatch $DB_CONTAINER
    if (-not $running) {
        throw "Docker container '$DB_CONTAINER' is not running. Start it with: docker start $DB_CONTAINER (or re-create it)."
    }

    # --- 1) API sanity (Confidence/Risk) ---
    $u = "http://127.0.0.1:8000/api/ai/run"
    $body = @{ text = "Dodaj task: Final readiness; rok: sutra; prioritet: high; status: open"; context = @{} } | ConvertTo-Json -Compress
    $r = Invoke-RestMethod -Method Post -Uri $u -ContentType "application/json" -Body $body

    $cr = $r.meta.confidence_risk
    if (-not $cr) { throw "meta.confidence_risk missing" }
    if (@("low","medium","high") -notcontains $cr.risk_level) { throw "risk_level invalid" }
    if (-not ($cr.assumption_count -is [int])) { throw "assumption_count not int" }

    $isNumeric = (
        ($cr.confidence_score -is [double]) -or
        ($cr.confidence_score -is [single]) -or
        ($cr.confidence_score -is [decimal]) -or
        ($cr.confidence_score -is [int])
    )
    if (-not $isNumeric) { throw "confidence_score not numeric" }

    # --- 2) DB sanity (table existence) ---
    $dbTablesRaw = docker exec -i $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -t -A -c "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"
    $dbTables = $dbTablesRaw -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }

    if ($dbTables -notcontains "outcome_feedback_loop") { throw "missing table outcome_feedback_loop" }
    if ($dbTables -notcontains "decision_outcome_registry") { throw "missing table decision_outcome_registry" }

    Write-Host "✅ PASS — FULL SYSTEM READY"
    Write-Host ("DB container: " + $DB_CONTAINER)
    Write-Host ("Tables: " + ($dbTables -join ", "))
    Write-Host ("risk_level=" + $cr.risk_level + " confidence_score=" + $cr.confidence_score + " assumption_count=" + $cr.assumption_count)

    $global:LASTEXITCODE = 0
}
catch {
    Write-Host "❌ FAIL — NOT READY"
    Write-Host $_.Exception.Message
    $global:LASTEXITCODE = 1
}
finally {
    Write-Host ("LASTEXITCODE=" + $global:LASTEXITCODE)
}

if ($Host.UI -and $Host.Name -eq "ConsoleHost") {
  Read-Host "Press ENTER to close"
}
