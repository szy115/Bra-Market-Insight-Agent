$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "_package-manager.ps1")

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Venv = Join-Path $Root ".venv"
$Python = $env:INSIGHT_PYTHON
$PythonArgs = @()

if (-not $Python) {
  $BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path $BundledPython) {
    $Python = $BundledPython
  } elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = "py"
    $PythonArgs = @("-3")
  } else {
    $Python = "python"
  }
}

Set-Location $Root
& $Python @PythonArgs -m venv $Venv
& (Join-Path $Venv "Scripts\python.exe") -m pip install --upgrade pip
& (Join-Path $Venv "Scripts\python.exe") -m pip install -e ".[dev]"

if (-not (Test-Path (Join-Path $Root ".env"))) {
  Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
}

$Frontend = Join-Path $Root "frontend"
if (Test-Path $Frontend) {
  $PackageManager = Get-InsightPackageManager
  Set-Location $Frontend
  Invoke-InsightPackageManager $PackageManager @("install")
  Set-Location $Root
}

Write-Host "Development environment ready."
Write-Host "Run backend:  .\scripts\dev.ps1"
Write-Host "Run frontend: .\scripts\dev-frontend.ps1"
Write-Host "Run both:     .\scripts\dev-all.ps1"
Write-Host "Install Agent Reach data tools: .\scripts\install-agent-reach.ps1"
