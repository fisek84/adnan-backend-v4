# scripts/clean_repo.ps1
# Lokalno čisti repozitorij od tipičnih artefakata (bez diranja source koda).

Write-Host "Cleaning repo..." 

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Obrisi __pycache__ direktorije
Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing __pycache__ directory: $($_.FullName)"
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }

# Obrisi .pyc fajlove
Get-ChildItem -Path . -Recurse -Include *.pyc -File -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing .pyc file: $($_.FullName)"
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }

# Obrisi .log fajlove
Get-ChildItem -Path . -Recurse -Include *.log -File -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing .log file: $($_.FullName)"
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }

# Obrisi output.json fajlove
Get-ChildItem -Path . -Recurse -Include output.json -File -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing output.json file: $($_.FullName)"
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }

Write-Host "Repo cleanup complete."
