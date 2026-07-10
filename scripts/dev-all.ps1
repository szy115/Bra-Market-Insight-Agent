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

$BackendReady = $false
$FrontendReady = $false
$Deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $Deadline) {
  try {
    $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 1
    $BackendReady = [bool]$Health.ok
  } catch {
    $BackendReady = $false
  }
  try {
    $FrontendResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:5173" -TimeoutSec 1
    $FrontendReady = $FrontendResponse.StatusCode -eq 200
  } catch {
    $FrontendReady = $false
  }
  if ($BackendReady -and $FrontendReady) {
    break
  }
  Start-Sleep -Milliseconds 500
}

if (-not ($BackendReady -and $FrontendReady)) {
  Write-Output "Development services did not become ready within 30 seconds."
  Write-Output "Backend error log:  $BackendErr"
  Write-Output "Frontend error log: $FrontendErr"
  & (Join-Path $PSScriptRoot "stop-dev.ps1")
  throw "Insight Agent startup failed. Review the .dev error logs."
}

Write-Output "Backend:  http://127.0.0.1:8000"
Write-Output "Frontend: http://127.0.0.1:5173"
Write-Output "Health:   backend and frontend are ready"
Write-Output "Logs:     .dev\backend.log and .dev\frontend.log"
Write-Output "Stop:     .\scripts\stop-dev.ps1"
