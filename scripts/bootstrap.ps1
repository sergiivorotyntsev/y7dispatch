<#
.SYNOPSIS
    Bootstrap script for Vehicle Transport Automation (Windows)
.DESCRIPTION
    Creates virtual environment, installs dependencies,
    copies .env.example to .env, and runs validation.
.EXAMPLE
    .\scripts\bootstrap.ps1
#>

param(
    [switch]$SkipValidate,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Vehicle Transport Automation - Setup  " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check Python version
Write-Host "[1/5] Checking Python..." -ForegroundColor Yellow
try {
    $pythonVersion = & py -3 --version 2>&1
    if ($pythonVersion -match "Python (\d+)\.(\d+)") {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 9)) {
            Write-Host "ERROR: Python 3.9+ required (found $pythonVersion)" -ForegroundColor Red
            exit 1
        }
        Write-Host "  Found: $pythonVersion" -ForegroundColor Green
    }
} catch {
    Write-Host "ERROR: Python not found. Install Python 3.9+ from python.org" -ForegroundColor Red
    exit 1
}

# Create virtual environment
Write-Host "[2/5] Creating virtual environment..." -ForegroundColor Yellow
$venvPath = ".\.venv"
if (Test-Path $venvPath) {
    if ($Force) {
        Write-Host "  Removing existing .venv (--Force)..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force $venvPath
    } else {
        Write-Host "  .venv already exists (use -Force to recreate)" -ForegroundColor Green
    }
}

if (-not (Test-Path $venvPath)) {
    & py -3 -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
    Write-Host "  Created: $venvPath" -ForegroundColor Green
}

# Activate and install dependencies
Write-Host "[3/5] Installing dependencies..." -ForegroundColor Yellow
$activateScript = "$venvPath\Scripts\Activate.ps1"
if (-not (Test-Path $activateScript)) {
    Write-Host "ERROR: Activation script not found at $activateScript" -ForegroundColor Red
    exit 1
}

# Run pip install in activated environment
& $venvPath\Scripts\python.exe -m pip install --upgrade pip -q
& $venvPath\Scripts\pip.exe install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install dependencies" -ForegroundColor Red
    exit 1
}
Write-Host "  Dependencies installed" -ForegroundColor Green

# Install dev dependencies if present
if (Test-Path "requirements-dev.txt") {
    Write-Host "  Installing dev dependencies..." -ForegroundColor Yellow
    & $venvPath\Scripts\pip.exe install -r requirements-dev.txt -q
}

# Copy .env.example to .env
Write-Host "[4/5] Setting up configuration..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "  Created .env from .env.example" -ForegroundColor Green
        Write-Host "  IMPORTANT: Edit .env with your credentials!" -ForegroundColor Yellow
    } else {
        Write-Host "  WARNING: .env.example not found" -ForegroundColor Yellow
    }
} else {
    Write-Host "  .env already exists" -ForegroundColor Green
}

# Create local_settings.json if not exists
$localSettingsPath = "config\local_settings.json"
if (-not (Test-Path "config")) {
    New-Item -ItemType Directory -Path "config" | Out-Null
}
if (-not (Test-Path $localSettingsPath)) {
    $defaultSettings = @{
        export_targets = @("sheets")
        enable_email_ingest = $false
        schema_version = 1
    } | ConvertTo-Json -Depth 3
    Set-Content -Path $localSettingsPath -Value $defaultSettings
    Write-Host "  Created config/local_settings.json" -ForegroundColor Green
}

# Run validation
Write-Host "[5/5] Running validation..." -ForegroundColor Yellow
if (-not $SkipValidate) {
    & $venvPath\Scripts\python.exe main.py doctor
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "WARNING: Some checks failed. Review output above." -ForegroundColor Yellow
    }
} else {
    Write-Host "  Skipped (use without -SkipValidate to run)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "           Setup Complete!             " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Activate: .\.venv\Scripts\Activate.ps1" -ForegroundColor Gray
Write-Host "  2. Edit .env with your credentials" -ForegroundColor Gray
Write-Host "  3. Run: python main.py doctor" -ForegroundColor Gray
Write-Host "  4. Test: python main.py extract <pdf_file>" -ForegroundColor Gray
Write-Host ""
