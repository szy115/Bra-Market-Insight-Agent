$ErrorActionPreference = "Stop"

$Project = $PSScriptRoot
$PidFile = Join-Path $Project ".wren-mcp.pid"
$OutLog = Join-Path $Project "wren-mcp.out.log"
$ErrLog = Join-Path $Project "wren-mcp.err.log"
$Port = 8080

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Output "Wren MCP is already listening at http://127.0.0.1:$Port/mcp (PID $($listener.OwningProcess))."
    exit 0
}

$projectArg = '--project="' + $Project + '"'
$process = Start-Process `
    -FilePath "wren.exe" `
    -ArgumentList @(
        "serve", "mcp",
        "--transport", "http",
        "--host", "127.0.0.1",
        "--port", "$Port",
        $projectArg,
        "--profile", "insight-agent-mysql"
    ) `
    -WorkingDirectory $Project `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -PassThru

Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ascii
Start-Sleep -Seconds 5

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $listener) {
    throw "Wren MCP did not start. Inspect $ErrLog"
}

Write-Output "Wren MCP started at http://127.0.0.1:$Port/mcp (PID $($listener.OwningProcess))."

