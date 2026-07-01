$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
  Get-Content $EnvFile | ForEach-Object {
    $Line = $_.Trim()
    if ($Line -and -not $Line.StartsWith("#") -and $Line.Contains("=")) {
      $Name, $Value = $Line.Split("=", 2)
      [Environment]::SetEnvironmentVariable($Name.Trim(), $Value.Trim(), "Process")
    }
  }
}

$env:INSIGHT_AGENT_HOME = $Root
$env:PYTHONPATH = Join-Path $Root "src"
Set-Location $Root
& $Python -m insight_agent.server
