$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "_package-manager.ps1")

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Frontend = Join-Path $Root "frontend"
$PackageManager = Get-InsightPackageManager

Set-Location $Frontend
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
  Invoke-InsightPackageManager $PackageManager @("install")
}

if ($PackageManager.Name -eq "npm") {
  Invoke-InsightPackageManager $PackageManager @("run", "dev")
} else {
  Invoke-InsightPackageManager $PackageManager @("dev")
}
