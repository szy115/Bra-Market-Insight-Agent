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
if ($LASTEXITCODE -ne 0) { throw "Creating the Python virtual environment failed with exit code $LASTEXITCODE." }
& (Join-Path $Venv "Scripts\python.exe") -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Upgrading pip failed with exit code $LASTEXITCODE." }
& (Join-Path $Venv "Scripts\python.exe") -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Installing Python dependencies failed with exit code $LASTEXITCODE." }

if (-not (Test-Path (Join-Path $Root ".env"))) {
  Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
}

$PackageManager = Get-InsightPackageManager
$Frontend = Join-Path $Root "frontend"
if (Test-Path $Frontend) {
  Set-Location $Frontend
  Invoke-InsightPackageManager $PackageManager @("install")
  Set-Location $Root
}

$ChartRuntime = Join-Path $Root "chart-runtime"
if (Test-Path $ChartRuntime) {
  Set-Location $ChartRuntime
  Invoke-InsightPackageManager $PackageManager @("install")
  Set-Location $Root
}

Write-Host "Development environment ready."
Write-Host "Run backend:  .\scripts\dev.ps1"
Write-Host "Run frontend: .\scripts\dev-frontend.ps1"
Write-Host "Run both:     .\scripts\dev-all.ps1"
Write-Host "Install Agent Reach data tools: .\scripts\install-agent-reach.ps1"
