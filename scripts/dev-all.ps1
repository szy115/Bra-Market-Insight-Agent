$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$DevDir = Join-Path $Root ".dev"
New-Item -ItemType Directory -Force -Path $DevDir | Out-Null

$BackendLog = Join-Path $DevDir "backend.log"
$BackendErr = Join-Path $DevDir "backend.err.log"
$FrontendLog = Join-Path $DevDir "frontend.log"
$FrontendErr = Join-Path $DevDir "frontend.err.log"
$BackendScript = Join-Path $PSScriptRoot "dev.ps1"
$FrontendScript = Join-Path $PSScriptRoot "dev-frontend.ps1"

$Backend = Start-Process -FilePath "powershell" `
  -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$BackendScript`"") `
  -WorkingDirectory $Root `
  -RedirectStandardOutput $BackendLog `
  -RedirectStandardError $BackendErr `
  -PassThru `
  -WindowStyle Hidden

$Frontend = Start-Process -FilePath "powershell" `
  -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$FrontendScript`"") `
  -WorkingDirectory $Root `
  -RedirectStandardOutput $FrontendLog `
  -RedirectStandardError $FrontendErr `
  -PassThru `
  -WindowStyle Hidden

@{
  backend = $Backend.Id
  frontend = $Frontend.Id
  started_at = (Get-Date).ToString("s")
} | ConvertTo-Json | Set-Content -Path (Join-Path $DevDir "pids.json") -Encoding UTF8

Write-Host "Backend:  http://127.0.0.1:8000"
Write-Host "Frontend: http://127.0.0.1:5173"
Write-Host "Logs:     .dev\backend.log and .dev\frontend.log"
Write-Host "Stop:     .\scripts\stop-dev.ps1"
