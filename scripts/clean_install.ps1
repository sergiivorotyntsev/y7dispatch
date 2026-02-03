# =============================================================================
# CLEAN INSTALL & UPDATE SCRIPT (Windows PowerShell)
# Vehicle Transport Automation (CENTRALDISPATCH)
#
# Usage:
#   .\scripts\clean_install.ps1           # Full clean install
#   .\scripts\clean_install.ps1 -KeepDb   # Keep database
#   .\scripts\clean_install.ps1 -Quick    # Quick reinstall (skip npm if exists)
# =============================================================================

param(
    [switch]$KeepDb,
    [switch]$Quick
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "║     CENTRALDISPATCH - Clean Install & Update              ║" -ForegroundColor Magenta
Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Magenta
Write-Host ""

# Get project root (parent of scripts folder)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host "Project root: $ProjectRoot" -ForegroundColor Cyan
Write-Host ""

# =============================================================================
# Step 1: Git Pull Latest Changes
# =============================================================================
Write-Host "[1/8] Pulling latest changes from Git..." -ForegroundColor Yellow
try {
    git fetch origin
    $currentBranch = git branch --show-current
    git pull origin $currentBranch
    Write-Host "  ✓ Git updated" -ForegroundColor Green
} catch {
    Write-Host "  ⚠ Git pull failed (may be OK if offline)" -ForegroundColor Yellow
}
Write-Host ""

# =============================================================================
# Step 2: Clean Python Cache & Build Artifacts
# =============================================================================
Write-Host "[2/8] Cleaning Python cache & build artifacts..." -ForegroundColor Yellow
Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path . -Recurse -Directory -Filter ".pytest_cache" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path . -Recurse -Directory -Filter ".ruff_cache" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path . -Recurse -Directory -Filter "*.egg-info" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path . -Recurse -File -Filter "*.pyc" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
if (Test-Path ".mypy_cache") { Remove-Item -Recurse -Force ".mypy_cache" -ErrorAction SilentlyContinue }
Write-Host "  ✓ Python cache cleaned" -ForegroundColor Green
Write-Host ""

# =============================================================================
# Step 3: Database Cleanup (Optional)
# =============================================================================
Write-Host "[3/8] Database management..." -ForegroundColor Yellow
if ($KeepDb) {
    Write-Host "  Keeping existing database (-KeepDb)" -ForegroundColor Cyan
} else {
    # Backup existing database before cleanup
    if (Test-Path "data\app.db") {
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $backupName = "data\app.db.backup.$timestamp"
        Copy-Item "data\app.db" $backupName
        Write-Host "  Backed up database to: $backupName" -ForegroundColor Cyan
    }

    # Remove SQLite databases for fresh start
    Remove-Item -Force "data\app.db" -ErrorAction SilentlyContinue
    Remove-Item -Force "data\training.db" -ErrorAction SilentlyContinue
    Remove-Item -Force "data\extractions.db" -ErrorAction SilentlyContinue
    Write-Host "  ✓ Database files removed (fresh start)" -ForegroundColor Green
}
Write-Host ""

# =============================================================================
# Step 4: Python Virtual Environment
# =============================================================================
Write-Host "[4/8] Setting up Python virtual environment..." -ForegroundColor Yellow

# Remove old venv and create fresh
if (Test-Path ".venv") {
    Write-Host "  Removing old .venv..."
    Remove-Item -Recurse -Force ".venv"
}

python -m venv .venv
& .\.venv\Scripts\Activate.ps1

Write-Host "  Upgrading pip..."
python -m pip install --upgrade pip -q

Write-Host "  Installing dependencies..."
pip install -r requirements.txt -q

if (Test-Path "requirements-dev.txt") {
    pip install -r requirements-dev.txt -q
}

Write-Host "  ✓ Python environment ready" -ForegroundColor Green
Write-Host ""

# =============================================================================
# Step 5: Frontend Dependencies
# =============================================================================
Write-Host "[5/8] Installing frontend dependencies..." -ForegroundColor Yellow
Push-Location web

if ($Quick -and (Test-Path "node_modules")) {
    Write-Host "  Skipping npm install (-Quick mode, node_modules exists)" -ForegroundColor Cyan
} else {
    # Clean node_modules for fresh install
    if (Test-Path "node_modules") { Remove-Item -Recurse -Force "node_modules" }
    if (Test-Path "package-lock.json") { Remove-Item -Force "package-lock.json" }

    npm install --silent
    Write-Host "  ✓ npm dependencies installed" -ForegroundColor Green
}
Pop-Location
Write-Host ""

# =============================================================================
# Step 6: Build Frontend
# =============================================================================
Write-Host "[6/8] Building frontend..." -ForegroundColor Yellow
Push-Location web
npm run build
Pop-Location
Write-Host "  ✓ Frontend built" -ForegroundColor Green
Write-Host ""

# =============================================================================
# Step 7: Copy .env if needed
# =============================================================================
Write-Host "[7/8] Configuration check..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "  Created .env from .env.example" -ForegroundColor Cyan
        Write-Host "  IMPORTANT: Edit .env with your credentials!" -ForegroundColor Yellow
    }
} else {
    Write-Host "  .env exists" -ForegroundColor Green
}

# Ensure directories exist
if (-not (Test-Path "config")) { New-Item -ItemType Directory -Path "config" | Out-Null }
if (-not (Test-Path "data")) { New-Item -ItemType Directory -Path "data" | Out-Null }
if (-not (Test-Path "static\uploads")) { New-Item -ItemType Directory -Path "static\uploads" -Force | Out-Null }
Write-Host ""

# =============================================================================
# Step 8: Run Tests to Verify
# =============================================================================
Write-Host "[8/8] Running tests to verify installation..." -ForegroundColor Yellow

# Run listing fields tests
python -m pytest tests/test_listing_fields.py -v --tb=short 2>&1 | Select-Object -First 40

Write-Host ""

# =============================================================================
# Summary
# =============================================================================
Write-Host ""
Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "║              Installation Complete!                       ║" -ForegroundColor Magenta
Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Magenta
Write-Host ""
Write-Host "To start the application:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Activate Python environment:"
Write-Host "     .\.venv\Scripts\Activate.ps1" -ForegroundColor Green
Write-Host ""
Write-Host "  2. Start backend (API server):"
Write-Host "     uvicorn api.main:app --reload --port 8000" -ForegroundColor Green
Write-Host ""
Write-Host "  3. Start frontend (in another terminal):"
Write-Host "     cd web; npm run dev" -ForegroundColor Green
Write-Host ""
Write-Host "  4. Open browser:"
Write-Host "     http://localhost:5173" -ForegroundColor Green -NoNewline
Write-Host " (frontend)"
Write-Host "     http://localhost:8000/docs" -ForegroundColor Green -NoNewline
Write-Host " (API docs)"
Write-Host ""
Write-Host "Quick commands:" -ForegroundColor Cyan
Write-Host "  • Run tests:   python -m pytest tests/ -v"
Write-Host "  • Lint:        ruff check ."
Write-Host "  • Doctor:      python main.py doctor"
Write-Host ""
