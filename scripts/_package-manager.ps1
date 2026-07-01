$ErrorActionPreference = "Stop"

$BundledNodeBin = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
if (Test-Path (Join-Path $BundledNodeBin "node.exe")) {
  $PathParts = $env:PATH -split ";"
  if ($PathParts -notcontains $BundledNodeBin) {
    $env:PATH = "$BundledNodeBin;$env:PATH"
  }
}

function Get-InsightPackageManager {
  if ($env:INSIGHT_PNPM) {
    return [pscustomobject]@{ Name = "pnpm"; Command = $env:INSIGHT_PNPM }
  }

  $BundledPnpm = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\bin\pnpm.cmd"
  if (Test-Path $BundledPnpm) {
    return [pscustomobject]@{ Name = "pnpm"; Command = $BundledPnpm }
  }

  $Pnpm = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
  if (-not $Pnpm) {
    $Pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
  }
  if ($Pnpm) {
    return [pscustomobject]@{ Name = "pnpm"; Command = $Pnpm.Source }
  }

  $Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if (-not $Npm) {
    $Npm = Get-Command npm -ErrorAction SilentlyContinue
  }
  if ($Npm) {
    return [pscustomobject]@{ Name = "npm"; Command = $Npm.Source }
  }

  throw "Neither pnpm nor npm was found. Install Node.js, or set INSIGHT_PNPM to pnpm.cmd."
}

function Invoke-InsightPackageManager {
  param(
    [Parameter(Mandatory = $true)] [object] $PackageManager,
    [Parameter(Mandatory = $true)] [string[]] $Arguments
  )

  & $PackageManager.Command @Arguments
}
