$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "_package-manager.ps1")

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
$Frontend = Join-Path $Root "frontend"

$env:PYTHONPATH = Join-Path $Root "src"
Set-Location $Root
& $Python -m ruff check .
& $Python -m pytest

$PackageManager = Get-InsightPackageManager
Set-Location $Frontend
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
  Invoke-InsightPackageManager $PackageManager @("install")
}

if ($PackageManager.Name -eq "npm") {
  Invoke-InsightPackageManager $PackageManager @("run", "build")
} else {
  Invoke-InsightPackageManager $PackageManager @("build")
}
