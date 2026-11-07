param(
    [string]$PythonPath = "python",
    [string]$NodePath = "node",
    [string]$NpmCliPath = "",
    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"
$dataDir = Join-Path $projectRoot "data"
$venvPython = Join-Path $backendDir ".venv/Scripts/python.exe"
$bundledRuntime = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies"
if ($PythonPath -eq "python" -and !(Get-Command python -ErrorAction SilentlyContinue)) {
    $bundledPython = Join-Path $bundledRuntime "python/python.exe"
    if (Test-Path $bundledPython) { $PythonPath = $bundledPython }
}
if ($NodePath -eq "node" -and !(Get-Command node -ErrorAction SilentlyContinue)) {
    $bundledNode = Join-Path $bundledRuntime "node/bin/node.exe"
    if (Test-Path $bundledNode) { $NodePath = $bundledNode }
}
if (!$NpmCliPath -and !(Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    $localNpm = Join-Path $projectRoot ".local/npm/package/bin/npm-cli.js"
    if (Test-Path $localNpm) { $NpmCliPath = $localNpm }
    else { throw "Install Node.js with npm, reopen PowerShell, and run this script again." }
}

function Assert-Success([string]$Action) {
    if ($LASTEXITCODE -ne 0) { throw "$Action failed (exit $LASTEXITCODE)." }
}

function Invoke-Npm([string[]]$NpmArguments) {
    if ($NpmCliPath) { & $NodePath $NpmCliPath @NpmArguments }
    else { & npm.cmd @NpmArguments }
    Assert-Success "npm"
}

& $NodePath --version
Assert-Success "Node.js check"
if (!(Test-Path $venvPython)) {
    & $PythonPath -c "import sys; assert (3, 11) <= sys.version_info[:2] <= (3, 13), 'Use Python 3.11, 3.12 or 3.13'"
    Assert-Success "Python check"
    & $PythonPath -m venv (Join-Path $backendDir ".venv")
    Assert-Success "Virtual environment creation"
}

$requirements = Join-Path $backendDir "requirements.txt"
$requirementsHash = (Get-FileHash $requirements).Hash
$stamp = Join-Path $backendDir ".venv/requirements.sha256"
if (!(Test-Path $stamp) -or (Get-Content $stamp -Raw).Trim() -ne $requirementsHash) {
    & $venvPython -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    Assert-Success "CPU PyTorch installation"
    & $venvPython -m pip install -r $requirements
    Assert-Success "Backend dependency installation"
    Set-Content $stamp $requirementsHash
}

Push-Location $frontendDir
try {
    if (!(Test-Path "node_modules/next/dist/bin/next")) { Invoke-Npm @("ci") }
} finally { Pop-Location }

New-Item -ItemType Directory -Force $dataDir | Out-Null
$secretPath = Join-Path $dataDir "local-jwt-secret.txt"
if (!(Test-Path $secretPath)) {
    $secret = & $venvPython -c "import secrets; print(secrets.token_hex(32))"
    Assert-Success "Local secret generation"
    Set-Content $secretPath $secret
}
if ($SetupOnly) { Write-Host "Local dependencies are ready."; return }

foreach ($port in @(8000, 3000)) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
    try { $listener.Start() }
    catch { throw "Port $port is already in use. Stop that process before starting LinguaLink." }
    finally { $listener.Stop() }
}

$env:DATABASE_URL = "sqlite:///" + (Join-Path $dataDir "lingualink.db").Replace('\', '/')
$env:JWT_SECRET = (Get-Content $secretPath -Raw).Trim()
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
if (!$env:HF_HOME) { $env:HF_HOME = Join-Path $dataDir "hf-cache" }
$logDir = Join-Path $dataDir "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$api = $null
$web = $null
try {
    $api = Start-Process -FilePath $venvPython -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir "api.log") -RedirectStandardError (Join-Path $logDir "api-error.log")
    $nextCli = Join-Path $frontendDir "node_modules/next/dist/bin/next"
    $web = Start-Process -FilePath (Get-Command $NodePath).Source -ArgumentList @(('"' + $nextCli + '"'), "dev", "--hostname", "127.0.0.1", "--port", "3000") -WorkingDirectory $frontendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir "web.log") -RedirectStandardError (Join-Path $logDir "web-error.log")
    Write-Host "LinguaLink: http://localhost:3000"
    Write-Host "API docs: http://localhost:8000/docs"
    Write-Host "Logs: $logDir"
    Write-Host "Translation settings are read from .env. NLLB downloads its model on first use."
    Write-Host "Keep this window open; Ctrl+C stops both servers."
    while (!$api.HasExited -and !$web.HasExited) { Start-Sleep -Seconds 1 }
    throw "A server stopped. Check the logs in $logDir."
} finally {
    foreach ($server in @($web, $api)) {
        if ($null -ne $server -and !$server.HasExited) {
            # Next.js launches a worker; stop the whole process tree.
            & taskkill.exe /PID $server.Id /T /F | Out-Null
        }
    }
}
