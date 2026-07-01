$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$PidFile = Join-Path $Root ".dev\pids.json"

function Stop-InsightProcessTree {
  param([Parameter(Mandatory = $true)] [int] $TargetProcessId)

  $Children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $TargetProcessId" -ErrorAction SilentlyContinue
  foreach ($Child in $Children) {
    Stop-InsightProcessTree -TargetProcessId $Child.ProcessId
  }

  $Process = Get-Process -Id $TargetProcessId -ErrorAction SilentlyContinue
  if ($Process) {
    Stop-Process -Id $TargetProcessId -ErrorAction SilentlyContinue
    Write-Host "Stopped process $TargetProcessId."
  }
}

$PortProcessIds = Get-NetTCPConnection -LocalPort 8000, 5173 -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique

if (-not (Test-Path $PidFile)) {
  foreach ($ProcessId in $PortProcessIds) {
    Stop-InsightProcessTree -TargetProcessId $ProcessId
  }
  if (-not $PortProcessIds) {
    Write-Host "No .dev\pids.json file found and no dev ports are listening."
  }
  exit 0
}

$Pids = Get-Content -Raw $PidFile | ConvertFrom-Json
$AllProcessIds = @($Pids.backend, $Pids.frontend) + $PortProcessIds | Where-Object { $_ } | Select-Object -Unique
foreach ($ProcessId in $AllProcessIds) {
  Stop-InsightProcessTree -TargetProcessId $ProcessId
}
