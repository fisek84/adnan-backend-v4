Write-Host "Testiranje kreiranja cilja u Notionu" -ForegroundColor Cyan

$BaseUrl = "http://127.0.0.1:8000"
$ApiPath = "/api/ceo-console/command"

# Prompt za kreiranje cilja
$prompt = "Kreiraj cilj 'Povećati prodaju za 20% u narednih 60 dana' sa prioritetom High i rokom 60 dana."

# Funkcija za slanje POST zahteva sa JSON podacima
function PostJson($path, $obj) {
    return Invoke-RestMethod -Method Post -Uri ($BaseUrl + $path) -ContentType "application/json" -Body ($obj | ConvertTo-Json -Depth 80)
}

# Aktiviranje Notion ops (ako je potrebno)
Write-Host "Aktiviranje Notion Ops..." -ForegroundColor Cyan
$response_activation = PostJson "/api/ceo-console/command" @{ text = "Aktiviraj Notion Ops za kreiranje cilja." }
if (-not $response_activation.ok) { Write-Host "Greška: Notion Ops nije aktiviran!" -ForegroundColor Red; exit 1 }
Write-Host "Notion Ops aktiviran" -ForegroundColor Green

# Slanje komande za kreiranje cilja
Write-Host "Slanje komande za kreiranje cilja..." -ForegroundColor Cyan
$response = PostJson $ApiPath @{ text = $prompt }

# Proverite da li je vraćen odgovarajući rezultat
if (-not $response.ok) {
    Write-Host "Greška: Odgovor nije uspešan." -ForegroundColor Red
    exit 1
}

Write-Host "Zahtev za kreiranje cilja je uspešno poslat!" -ForegroundColor Green

# Ispisivanje svih predloženih komandi (proposed_commands)
if ($response.PSObject.Properties.Name -contains "proposed_commands") {
    $proposedCommands = $response.proposed_commands
    if ($proposedCommands.Count -gt 0) {
        Write-Host "Predložene komande: " -ForegroundColor Green
        $proposedCommands | ForEach-Object { Write-Host $_.command }
    } else {
        Write-Host "Nema predloženih komandi." -ForegroundColor Red
    }
} else {
    Write-Host "Nema predloženih komandi." -ForegroundColor Red
}

# Testiranje da li je Notion ispravno ažuriran (sa primerom sa execute/raw)
if ($response.PSObject.Properties.Name -contains "approval_id") {
    $approvalId = $response.approval_id
    Write-Host "Čekanje na odobrenje sa approval_id: $approvalId" -ForegroundColor Cyan

    # Simuliraj odobrenje komande (ako je potrebno)
    $approveResponse = PostJson "/api/ai-ops/approval/approve" @{ approval_id = $approvalId }
    if ($approveResponse.execution_state -eq "COMPLETED") {
        Write-Host "Komanda je uspešno odobrena i izvršena." -ForegroundColor Green
    } else {
        Write-Host "Nije moguće odobriti komandu. Status: $($approveResponse.execution_state)" -ForegroundColor Red
    }
} else {
    Write-Host "Approval ID nije prisutan, proverite da li je komanda validna." -ForegroundColor Red
}

Write-Host "Testiranje završeno!" -ForegroundColor Cyan
