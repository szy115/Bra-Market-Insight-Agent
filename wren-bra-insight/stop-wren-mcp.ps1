$ErrorActionPreference = "Stop"

$PidFile = Join-Path $PSScriptRoot ".wren-mcp.pid"
if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Output "No Wren MCP PID file was found."
    exit 0
}

$processId = [int](Get-Content -LiteralPath $PidFile -Raw).Trim()
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
if ($process -and $process.Name -match '^wren(\.exe)?$' -and $process.CommandLine -match 'serve\s+mcp') {
    Stop-Process -Id $processId
    Write-Output "Wren MCP stopped (PID $processId)."
} elseif ($process) {
    throw "PID $processId is not a Wren MCP process; it was left untouched."
} else {
    Write-Output "Wren MCP process $processId is no longer running."
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue

