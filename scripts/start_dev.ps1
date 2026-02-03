# =============================================================================
# START DEVELOPMENT SERVERS (Windows PowerShell)
# Starts both backend (FastAPI) and frontend (Vite) in parallel
#
# Usage:
#   .\scripts\start_dev.ps1
#   .\scripts\start_dev.ps1 -BackendOnly
#   .\scripts\start_dev.ps1 -FrontendOnly
# =============================================================================

param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

$ErrorActionPreference = "Stop"

# Get project root (parent of scripts folder)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

# Activate virtual environment
if (Test-Path ".venv\Scripts\Activate.ps1") {
    & .\.venv\Scripts\Activate.ps1
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  CENTRALDISPATCH - Development Server   " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

if ($FrontendOnly) {
    Write-Host "Starting frontend only..." -ForegroundColor Green
    Write-Host "  -> http://localhost:5173"
    Write-Host ""
    Push-Location web
    npm run dev
    Pop-Location
}
elseif ($BackendOnly) {
    Write-Host "Starting backend only..." -ForegroundColor Green
    Write-Host "  -> http://localhost:8000"
    Write-Host "  -> http://localhost:8000/docs (API docs)"
    Write-Host ""
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
}
else {
    Write-Host "Starting both backend and frontend in separate windows..." -ForegroundColor Green
    Write-Host ""
    Write-Host "Backend:" -ForegroundColor Yellow
    Write-Host "  -> http://localhost:8000"
    Write-Host "  -> http://localhost:8000/docs (API docs)"
    Write-Host ""
    Write-Host "Frontend:" -ForegroundColor Yellow
    Write-Host "  -> http://localhost:5173"
    Write-Host ""

    # Start backend in new window
    $backendCmd = "Set-Location '$ProjectRoot'; "
    $backendCmd += "if (Test-Path '.venv\Scripts\Activate.ps1') { & '.\.venv\Scripts\Activate.ps1' }; "
    $backendCmd += "uvicorn api.main:app --reload --host 0.0.0.0 --port 8000; "
    $backendCmd += "Read-Host 'Press Enter to close'"

    Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd

    # Give backend time to start
    Start-Sleep -Seconds 2

    # Start frontend in new window
    $frontendCmd = "Set-Location '$ProjectRoot\web'; npm run dev; Read-Host 'Press Enter to close'"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd

    Write-Host "Two new PowerShell windows opened:" -ForegroundColor Cyan
    Write-Host "  - Backend server window"
    Write-Host "  - Frontend server window"
    Write-Host ""
    Write-Host "Close those windows to stop the servers." -ForegroundColor Cyan
}
