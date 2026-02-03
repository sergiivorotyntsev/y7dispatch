#!/bin/bash
# Bootstrap script for Vehicle Transport Automation (Linux/Mac)
# Usage: ./scripts/bootstrap.sh

set -e

echo "========================================"
echo " Vehicle Transport Automation - Setup  "
echo "========================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Check Python version
echo -e "${YELLOW}[1/5] Checking Python...${NC}"
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
    MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
    MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)

    if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 9 ]); then
        echo -e "${RED}ERROR: Python 3.9+ required (found $PYTHON_VERSION)${NC}"
        exit 1
    fi
    echo -e "  Found: Python ${GREEN}$PYTHON_VERSION${NC}"
else
    echo -e "${RED}ERROR: Python3 not found${NC}"
    exit 1
fi

# Create virtual environment
echo -e "${YELLOW}[2/5] Creating virtual environment...${NC}"
if [ -d ".venv" ]; then
    if [ "$1" == "--force" ]; then
        echo "  Removing existing .venv..."
        rm -rf .venv
    else
        echo -e "  ${GREEN}.venv already exists${NC} (use --force to recreate)"
    fi
fi

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo -e "  ${GREEN}Created: .venv${NC}"
fi

# Activate and install dependencies
echo -e "${YELLOW}[3/5] Installing dependencies...${NC}"
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo -e "  ${GREEN}Dependencies installed${NC}"

# Install dev dependencies if present
if [ -f "requirements-dev.txt" ]; then
    echo "  Installing dev dependencies..."
    pip install -r requirements-dev.txt -q
fi

# Copy .env.example to .env
echo -e "${YELLOW}[4/5] Setting up configuration...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "  ${GREEN}Created .env from .env.example${NC}"
        echo -e "  ${YELLOW}IMPORTANT: Edit .env with your credentials!${NC}"
    else
        echo -e "  ${YELLOW}WARNING: .env.example not found${NC}"
    fi
else
    echo -e "  ${GREEN}.env already exists${NC}"
fi

# Create local_settings.json if not exists
mkdir -p config
if [ ! -f "config/local_settings.json" ]; then
    cat > config/local_settings.json << 'EOF'
{
    "export_targets": ["sheets"],
    "enable_email_ingest": false,
    "schema_version": 1
}
EOF
    echo -e "  ${GREEN}Created config/local_settings.json${NC}"
fi

# Run validation
echo -e "${YELLOW}[5/5] Running validation...${NC}"
if [ "$1" != "--skip-validate" ]; then
    python main.py doctor || echo -e "\n${YELLOW}WARNING: Some checks failed. Review output above.${NC}"
else
    echo "  Skipped"
fi

echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}           Setup Complete!             ${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Activate: source .venv/bin/activate"
echo "  2. Edit .env with your credentials"
echo "  3. Run: python main.py doctor"
echo "  4. Test: python main.py extract <pdf_file>"
echo ""
