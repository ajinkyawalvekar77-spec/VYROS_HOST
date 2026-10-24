param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$engineRoot = $PSScriptRoot
$backendRoot = Join-Path (Split-Path -Parent $engineRoot) "optiqo-backend"
$frontendRoot = Join-Path $engineRoot "frontend"
$python = Join-Path $engineRoot ".venv\Scripts\python.exe"
$node = (Get-Command node.exe -ErrorAction Stop).Source
$envFile = Join-Path $frontendRoot ".env"
$envExample = Join-Path $frontendRoot ".env.example"

foreach ($requiredPath in @($backendRoot, $frontendRoot, $python, $node)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required Optiqo path was not found: $requiredPath"
    }
}

if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath $envExample -Destination $envFile
    Write-Host "Created frontend/.env from the checked-in example."
}

$env:OPTIQO_ENGINE_PATH = $engineRoot
$env:PYTHONPATH = Split-Path -Parent $engineRoot
$env:OPTIQO_ALLOW_LOCAL_DEVELOPMENT_ACCESS = "true"

foreach ($port in @(8000, 5173)) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        throw "Port $port is already in use (PID $($listener.OwningProcess)). Stop that service before starting Optiqo."
    }
}

$backendProcess = $null
$frontendProcess = $null
try {
    $backendProcess = Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "optiqo_backend.main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $backendRoot -PassThru
    $frontendProcess = Start-Process -FilePath $node `
        -ArgumentList @("node_modules\vite\bin\vite.js", "--host", "127.0.0.1") `
        -WorkingDirectory $frontendRoot -PassThru

    $backendReady = $false
    $frontendReady = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if (-not $backendReady) {
            try {
                $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
                $backendReady = $health.status -eq "running"
            } catch {
                $backendReady = $false
            }
        }
        if (-not $frontendReady) {
            try {
                $null = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -TimeoutSec 2 -UseBasicParsing
                $frontendReady = $true
            } catch {
                $frontendReady = $false
            }
        }
        if ($backendReady -and $frontendReady) { break }
        Start-Sleep -Seconds 2
    }

    if (-not $backendReady -or -not $frontendReady) {
        throw "Optiqo startup timed out. Check the backend and frontend terminal windows for errors."
    }

    Write-Host "Optiqo frontend: http://127.0.0.1:5173"
    Write-Host "Optiqo API docs: http://127.0.0.1:8000/docs"
    if (-not $health.engine_ready) {
        Write-Warning "The API is running, but the AI/ML engine is not ready: $($health.engine_error)"
    }
    Write-Warning "Local development access is restricted to loopback. Do not expose this backend publicly."
    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:5173"
    }
} catch {
    foreach ($process in @($frontendProcess, $backendProcess)) {
        if ($process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id
        }
    }
    throw
}
