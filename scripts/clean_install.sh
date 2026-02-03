#!/bin/bash
# =============================================================================
# CLEAN INSTALL & UPDATE SCRIPT
# Vehicle Transport Automation (CENTRALDISPATCH)
#
# Usage:
#   ./scripts/clean_install.sh           # Full clean install
#   ./scripts/clean_install.sh --keep-db # Keep database
#   ./scripts/clean_install.sh --quick   # Quick reinstall (skip npm install if exists)
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Parse arguments
KEEP_DB=false
QUICK=false
for arg in "$@"; do
    case $arg in
        --keep-db) KEEP_DB=true ;;
        --quick) QUICK=true ;;
    esac
done

echo ""
echo -e "${MAGENTA}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${MAGENTA}║     CENTRALDISPATCH - Clean Install & Update              ║${NC}"
echo -e "${MAGENTA}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo -e "${CYAN}Project root: ${PROJECT_ROOT}${NC}"
echo ""

# =============================================================================
# Step 1: Git Pull Latest Changes
# =============================================================================
echo -e "${YELLOW}[1/8] Pulling latest changes from Git...${NC}"
git fetch origin
git pull origin "$(git branch --show-current)" || true
echo -e "${GREEN}  ✓ Git updated${NC}"
echo ""

# =============================================================================
# Step 2: Clean Python Cache & Build Artifacts
# =============================================================================
echo -e "${YELLOW}[2/8] Cleaning Python cache & build artifacts...${NC}"
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
rm -rf .mypy_cache 2>/dev/null || true
echo -e "${GREEN}  ✓ Python cache cleaned${NC}"
echo ""

# =============================================================================
# Step 3: Database Cleanup (Optional)
# =============================================================================
echo -e "${YELLOW}[3/8] Database management...${NC}"
if [ "$KEEP_DB" = true ]; then
    echo -e "  ${CYAN}Keeping existing database (--keep-db)${NC}"
else
    # Backup existing database before cleanup
    if [ -f "data/app.db" ]; then
        BACKUP_NAME="data/app.db.backup.$(date +%Y%m%d_%H%M%S)"
        cp "data/app.db" "$BACKUP_NAME"
        echo -e "  ${CYAN}Backed up database to: $BACKUP_NAME${NC}"
    fi

    # Remove SQLite databases for fresh start
    rm -f data/app.db 2>/dev/null || true
    rm -f data/training.db 2>/dev/null || true
    rm -f data/extractions.db 2>/dev/null || true
    echo -e "${GREEN}  ✓ Database files removed (fresh start)${NC}"
fi
echo ""

# =============================================================================
# Step 4: Python Virtual Environment
# =============================================================================
echo -e "${YELLOW}[4/8] Setting up Python virtual environment...${NC}"

# Remove old venv and create fresh
if [ -d ".venv" ]; then
    echo "  Removing old .venv..."
    rm -rf .venv
fi

python3 -m venv .venv
source .venv/bin/activate

echo "  Upgrading pip..."
pip install --upgrade pip -q

echo "  Installing dependencies..."
pip install -r requirements.txt -q

if [ -f "requirements-dev.txt" ]; then
    pip install -r requirements-dev.txt -q
fi

echo -e "${GREEN}  ✓ Python environment ready${NC}"
echo ""

# =============================================================================
# Step 5: Frontend Dependencies
# =============================================================================
echo -e "${YELLOW}[5/8] Installing frontend dependencies...${NC}"
cd web

if [ "$QUICK" = true ] && [ -d "node_modules" ]; then
    echo -e "  ${CYAN}Skipping npm install (--quick mode, node_modules exists)${NC}"
else
    # Clean node_modules for fresh install
    rm -rf node_modules 2>/dev/null || true
    rm -f package-lock.json 2>/dev/null || true

    npm install --silent
    echo -e "${GREEN}  ✓ npm dependencies installed${NC}"
fi
cd "$PROJECT_ROOT"
echo ""

# =============================================================================
# Step 6: Build Frontend
# =============================================================================
echo -e "${YELLOW}[6/8] Building frontend...${NC}"
cd web
npm run build
cd "$PROJECT_ROOT"
echo -e "${GREEN}  ✓ Frontend built${NC}"
echo ""

# =============================================================================
# Step 7: Copy .env if needed
# =============================================================================
echo -e "${YELLOW}[7/8] Configuration check...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "  ${CYAN}Created .env from .env.example${NC}"
        echo -e "  ${YELLOW}IMPORTANT: Edit .env with your credentials!${NC}"
    fi
else
    echo -e "  ${GREEN}.env exists${NC}"
fi

# Ensure config directory exists
mkdir -p config data static/uploads
echo ""

# =============================================================================
# Step 8: Run Tests to Verify
# =============================================================================
echo -e "${YELLOW}[8/8] Running tests to verify installation...${NC}"
source .venv/bin/activate

# Run listing fields tests (most critical)
python -m pytest tests/test_listing_fields.py -v --tb=short 2>&1 | head -40
TEST_RESULT=$?

echo ""
if [ $TEST_RESULT -eq 0 ]; then
    echo -e "${GREEN}  ✓ All tests passed!${NC}"
else
    echo -e "${YELLOW}  ⚠ Some tests failed (see output above)${NC}"
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo -e "${MAGENTA}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${MAGENTA}║              Installation Complete!                       ║${NC}"
echo -e "${MAGENTA}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}To start the application:${NC}"
echo ""
echo "  1. Activate Python environment:"
echo -e "     ${GREEN}source .venv/bin/activate${NC}"
echo ""
echo "  2. Start backend (API server):"
echo -e "     ${GREEN}uvicorn api.main:app --reload --port 8000${NC}"
echo ""
echo "  3. Start frontend (in another terminal):"
echo -e "     ${GREEN}cd web && npm run dev${NC}"
echo ""
echo "  4. Or run both with a single command:"
echo -e "     ${GREEN}./scripts/start_dev.sh${NC}"
echo ""
echo "  5. Open browser:"
echo -e "     ${GREEN}http://localhost:5173${NC} (frontend)"
echo -e "     ${GREEN}http://localhost:8000/docs${NC} (API docs)"
echo ""
echo -e "${CYAN}Quick commands:${NC}"
echo "  • Run tests:   python -m pytest tests/ -v"
echo "  • Lint:        ruff check ."
echo "  • Doctor:      python main.py doctor"
echo ""
