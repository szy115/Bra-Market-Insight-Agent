$ErrorActionPreference = "Stop"

$AgentReachVenv = if ($env:AGENT_REACH_VENV) {
  $env:AGENT_REACH_VENV
} else {
  Join-Path $env:USERPROFILE ".agent-reach-venv"
}

$AgentReachScripts = Join-Path $AgentReachVenv "Scripts"
$env:PATH = "$AgentReachScripts;$env:PATH"
$UserNpmBin = Join-Path $env:APPDATA "npm"
$AgentReachBin = Join-Path $env:USERPROFILE ".agent-reach\bin"
$BundledNodeBin = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
if (Test-Path (Join-Path $BundledNodeBin "node.exe")) {
  $env:PATH = "$BundledNodeBin;$env:PATH"
}
foreach ($NodePath in @("$env:ProgramFiles\nodejs", "${env:ProgramFiles(x86)}\nodejs", "$env:LOCALAPPDATA\Programs\nodejs", $UserNpmBin, $AgentReachBin)) {
  if ($NodePath -and (Test-Path $NodePath)) {
    $env:PATH = "$NodePath;$env:PATH"
  }
}

Write-Host "Command availability:"
foreach ($Name in @("node", "npm", "agent-reach", "mcporter", "opencli", "rdt")) {
  $Command = Get-Command $Name -ErrorAction SilentlyContinue
  if ($Command) {
    Write-Host "  OK  $Name -> $($Command.Source)"
  } else {
    Write-Host "  MISS $Name"
  }
}

if (Get-Command mcporter -ErrorAction SilentlyContinue) {
  $McporterConfig = Join-Path $env:USERPROFILE ".agent-reach\mcporter.json"
  Write-Host ""
  Write-Host "Project mcporter config:"
  if (Test-Path $McporterConfig) {
    mcporter --config $McporterConfig config list --json
  } else {
    Write-Host "  MISS $McporterConfig"
  }
}

if (Get-Command agent-reach -ErrorAction SilentlyContinue) {
  Write-Host ""
  agent-reach doctor
}

if (Get-Command opencli -ErrorAction SilentlyContinue) {
  Write-Host ""
  Write-Host "OpenCLI doctor:"
  opencli doctor
}
