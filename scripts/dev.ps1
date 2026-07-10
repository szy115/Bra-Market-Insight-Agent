$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

$EnvFile = Join-Path $Root ".env"
function ConvertFrom-InsightEnvValue {
  param([Parameter(Mandatory = $true)] [string] $Value)

  $Normalized = $Value.Trim()
  if ($Normalized.Length -ge 2 -and $Normalized[0] -in @('"', "'")) {
    $Quote = [string]$Normalized[0]
    $ClosingIndex = $Normalized.LastIndexOf($Quote)
    if ($ClosingIndex -gt 0) {
      $Normalized = $Normalized.Substring(1, $ClosingIndex - 1)
      if ($Quote -eq '"') {
        $Normalized = $Normalized.Replace('\"', '"').Replace('\\', '\')
      }
    }
  } elseif ($Normalized.Contains(" #")) {
    $Normalized = $Normalized.Split(" #", 2)[0].TrimEnd()
  }
  return $Normalized
}

if (Test-Path $EnvFile) {
  Get-Content $EnvFile | ForEach-Object {
    $Line = $_.Trim()
    if ($Line -and -not $Line.StartsWith("#") -and $Line.Contains("=")) {
      $Name, $Value = $Line.Split("=", 2)
      [Environment]::SetEnvironmentVariable($Name.Trim(), (ConvertFrom-InsightEnvValue $Value), "Process")
    }
  }
}

$env:INSIGHT_AGENT_HOME = $Root
$env:PYTHONPATH = Join-Path $Root "src"
Set-Location $Root
& $Python -m insight_agent.server
exit $LASTEXITCODE
