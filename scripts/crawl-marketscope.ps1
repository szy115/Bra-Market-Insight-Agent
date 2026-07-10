param(
  [Parameter(Mandatory = $true)]
  [string] $Url,

  [string] $Output = "",

  [string] $Profile = "",

  [ValidateRange(1, 30)]
  [int] $SettleSeconds = 5,

  [ValidateRange(1, 200)]
  [int] $MaxEntries = 100,

  [switch] $PassiveOnly,

  [switch] $KeepTab
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
$env:PYTHONPATH = Join-Path $Root "src"

$CliArgs = @(
  "-m",
  "insight_agent.ingestion.marketscope",
  "--timeout",
  "60"
)

if ($Profile) {
  $CliArgs += @("--profile", $Profile)
}

$CliArgs += @(
  "capture",
  $Url,
  "--settle-seconds",
  "$SettleSeconds",
  "--max-entries",
  "$MaxEntries"
)

if ($Output) {
  $CliArgs += @("--output", $Output)
}

if ($KeepTab) {
  $CliArgs += "--keep-tab"
}

if ($PassiveOnly) {
  $CliArgs += "--passive-only"
}

Set-Location $Root
& $Python @CliArgs
exit $LASTEXITCODE
