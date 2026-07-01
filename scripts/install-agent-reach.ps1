$ErrorActionPreference = "Stop"

$AgentReachVenv = if ($env:AGENT_REACH_VENV) {
  $env:AGENT_REACH_VENV
} else {
  Join-Path $env:USERPROFILE ".agent-reach-venv"
}

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

Write-Host "Installing Agent Reach into: $AgentReachVenv"
& $Python @PythonArgs -m venv $AgentReachVenv
$AgentReachPython = Join-Path $AgentReachVenv "Scripts\python.exe"
$AgentReachScripts = Join-Path $AgentReachVenv "Scripts"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$EnvFile = Join-Path $Root ".env"
$BundledNodeBin = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
$BundledBin = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\bin"
$NodeInstallBin = "$env:ProgramFiles\nodejs"
$UserNpmBin = Join-Path $env:APPDATA "npm"
$AgentReachBin = Join-Path $env:USERPROFILE ".agent-reach\bin"

New-Item -ItemType Directory -Force -Path $AgentReachBin | Out-Null
Set-Content -Path (Join-Path $AgentReachBin "true.cmd") -Value "@echo off`r`nexit /b 0" -Encoding ASCII

if (Test-Path (Join-Path $BundledNodeBin "node.exe")) {
  $env:PATH = "$BundledNodeBin;$env:PATH"
}
if (Test-Path $BundledBin) {
  $env:PATH = "$BundledBin;$env:PATH"
}
foreach ($PathItem in @($NodeInstallBin, $UserNpmBin, $AgentReachBin)) {
  if ($PathItem -and (Test-Path $PathItem)) {
    $env:PATH = "$PathItem;$env:PATH"
  }
}

function Set-LocalEnvValue {
  param(
    [Parameter(Mandatory = $true)] [string] $Name,
    [Parameter(Mandatory = $true)] [string] $Value
  )

  if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Root ".env.example") $EnvFile
  }
  $Lines = Get-Content $EnvFile
  $Updated = $false
  for ($Index = 0; $Index -lt $Lines.Count; $Index++) {
    $Line = $Lines[$Index].TrimStart()
    $Candidate = if ($Line.StartsWith("#")) { $Line.Substring(1).TrimStart() } else { $Line }
    if ($Candidate.StartsWith("$Name=")) {
      $Escaped = $Value.Replace("\", "\\")
      $Lines[$Index] = "$Name=""$Escaped"""
      $Updated = $true
      break
    }
  }
  if (-not $Updated) {
    if ($Lines.Count -gt 0 -and $Lines[-1].Trim()) {
      $Lines += ""
    }
    $Escaped = $Value.Replace("\", "\\")
    $Lines += "$Name=""$Escaped"""
  }
  Set-Content -Path $EnvFile -Value $Lines -Encoding UTF8
}

& $AgentReachPython -m pip install --upgrade pip
& $AgentReachPython -m pip install "https://github.com/Panniantong/agent-reach/archive/main.zip"

$env:PATH = "$AgentReachScripts;$env:PATH"
Set-LocalEnvValue -Name "AGENT_REACH_VENV" -Value $AgentReachVenv

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  $Winget = Get-Command winget -ErrorAction SilentlyContinue
  if ($Winget) {
    Write-Host "npm was not found. Installing Node.js LTS via winget..."
    winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements --silent
    $NodePaths = @(
      "$env:ProgramFiles\nodejs",
      "${env:ProgramFiles(x86)}\nodejs",
      "$env:LOCALAPPDATA\Programs\nodejs"
    ) | Where-Object { $_ -and (Test-Path $_) }
    foreach ($NodePath in $NodePaths) {
      $env:PATH = "$NodePath;$env:PATH"
    }
  }
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Write-Host "npm is still unavailable. OpenCLI cannot be installed yet."
  Write-Host "Install Node.js LTS from https://nodejs.org, then rerun: .\scripts\install-agent-reach.ps1"
  exit 1
}

Write-Host "Installing OpenCLI npm package..."
& npm.cmd install -g @jackwener/opencli

Write-Host "Installing Agent Reach channels: opencli,reddit"
& (Join-Path $AgentReachScripts "agent-reach.exe") install --env=auto --channels=opencli,reddit

Write-Host ""
Write-Host "Agent Reach install finished. Running doctor..."
& (Join-Path $AgentReachScripts "agent-reach.exe") doctor

Write-Host ""
Write-Host "Next manual step if OpenCLI reports extension missing:"
Write-Host "1. Install the OpenCLI Chrome extension from the Chrome Web Store."
Write-Host "2. Log in to Reddit in Chrome with a dedicated Reddit account."
Write-Host "3. Run: .\scripts\doctor-agent-reach.ps1"
