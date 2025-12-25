# scripts/_canon_env.ps1

function Stop-Port8000 {
  Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
  Get-Process uvicorn -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Get-Process python  -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 600
}

function Wait-Port8000 {
  param([int]$Tries = 80)
  for ($i=0; $i -lt $Tries; $i++) {
    if ((Test-NetConnection 127.0.0.1 -Port 8000 -WarningAction SilentlyContinue).TcpTestSucceeded) { return }
    Start-Sleep -Milliseconds 250
  }
  throw "Server not ready on 8000"
}
