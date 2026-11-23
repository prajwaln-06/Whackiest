param([switch]$Setup, [ValidateSet(0, 3000, 3001)][int]$FrontendPort = 0)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$python = Join-Path $root '.venv\Scripts\python.exe'
$logDir = Join-Path $root '.run'
$frontendBinary = Join-Path $frontend 'node_modules\next\dist\bin\next'
$processes = @()

function Assert-Success([string]$Description) {
    if ($LASTEXITCODE -ne 0) { throw "$Description failed with exit code $LASTEXITCODE." }
}

function Test-AvailablePort([int]$Port) {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try { $listener.Start(); return $true }
    catch [Net.Sockets.SocketException] { return $false }
    finally { $listener.Stop() }
}

function Start-ServiceProcess([string]$Name, [string]$Executable, [string[]]$Arguments, [string]$Directory) {
    $options = @{
        FilePath = $Executable; ArgumentList = $Arguments; WorkingDirectory = $Directory; WindowStyle = 'Hidden'
        RedirectStandardOutput = (Join-Path $logDir "$Name.out.log"); RedirectStandardError = (Join-Path $logDir "$Name.err.log")
    }
    Start-Process @options -PassThru
}

function Stop-ServiceProcess([int]$ProcessId) {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) { Stop-ServiceProcess $child.ProcessId }
    Stop-Process -Id $ProcessId -ErrorAction SilentlyContinue
}

if (!(Test-Path -LiteralPath (Join-Path $root '.env'))) {
    Copy-Item -LiteralPath (Join-Path $root '.env.example') -Destination (Join-Path $root '.env')
}
$node = (Get-Command node -ErrorAction Stop).Source
if (!(Test-Path -LiteralPath $python)) {
    & python -c "import sys; assert sys.version_info >= (3, 11), 'Install Python 3.11 or newer'"
    Assert-Success 'Python version check'
    & python -m venv (Join-Path $root '.venv')
    Assert-Success 'Virtual environment creation'
    $Setup = $true
}
& $python -c "import fastapi, playwright, aiosqlite, pydantic_settings, openai, pypdf" 2>$null
if ($Setup -or $LASTEXITCODE -ne 0) {
    & $python -m pip install -r (Join-Path $backend 'requirements.txt')
    Assert-Success 'Python dependency installation'
}
& $python -m playwright install chromium
Assert-Success 'Chromium installation'
if ($Setup -or !(Test-Path -LiteralPath $frontendBinary)) {
    Push-Location -LiteralPath $frontend
    try { & npm.cmd ci; Assert-Success 'Frontend dependency installation' }
    finally { Pop-Location }
}

if (!$FrontendPort) {
    $FrontendPort = 3000
    if (!(Test-AvailablePort $FrontendPort)) { $FrontendPort = 3001 }
}
foreach ($port in @(8000, 8001, $FrontendPort)) {
    if (!(Test-AvailablePort $port)) { throw "Port $port is unavailable. Close the service using it and retry." }
}
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

try {
    $processes += Start-ServiceProcess 'civicgrid' $python @('-m', 'uvicorn', 'demo_portal.app:app', '--host', '127.0.0.1', '--port', '8001') $root
    # No reload or extra workers. app.main uses a Windows Proactor loop for Chromium subprocesses.
    $processes += Start-ServiceProcess 'agent' $python @('-m', 'app.main') $backend
    $processes += Start-ServiceProcess 'workspace' $node @('node_modules/next/dist/bin/next', 'dev', '--hostname', '127.0.0.1', '--port', "$FrontendPort") $frontend
    $workspace = "http://127.0.0.1:$FrontendPort"
    foreach ($endpoint in @('http://127.0.0.1:8001', 'http://127.0.0.1:8000/api/health', $workspace)) {
        $deadline = (Get-Date).AddSeconds(75)
        while ($true) {
            if ($processes | Where-Object { $_.HasExited }) { throw "A service exited. See logs in $logDir." }
            try { Invoke-WebRequest -Uri $endpoint -UseBasicParsing -TimeoutSec 4 | Out-Null; break }
            catch { if ((Get-Date) -gt $deadline) { throw "Service unavailable at $endpoint. See logs in $logDir." } }
            Start-Sleep -Milliseconds 350
        }
    }
    Write-Host "WebMorph is ready at $workspace"
    Write-Host 'CivicGrid is at http://localhost:8001. Press Ctrl+C to stop all services.'
    while ($true) {
        if ($processes | Where-Object { $_.HasExited }) { throw "A service exited. See logs in $logDir." }
        Start-Sleep -Seconds 1
    }
}
finally {
    foreach ($process in $processes) { if (!$process.HasExited) { Stop-ServiceProcess $process.Id } }
}
