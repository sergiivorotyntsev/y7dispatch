#!/bin/bash
# =============================================================================
# START DEVELOPMENT SERVERS
# Starts both backend (FastAPI) and frontend (Vite) in parallel
#
# Usage:
#   ./scripts/start_dev.sh
#   ./scripts/start_dev.sh --backend-only
#   ./scripts/start_dev.sh --frontend-only
# =============================================================================

set -e

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Parse arguments
BACKEND_ONLY=false
FRONTEND_ONLY=false
for arg in "$@"; do
    case $arg in
        --backend-only) BACKEND_ONLY=true ;;
        --frontend-only) FRONTEND_ONLY=true ;;
    esac
done

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

echo ""
echo -e "${CYAN}╔═══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   CENTRALDISPATCH - Development Server    ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════════╝${NC}"
echo ""

# Function to cleanup on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}Stopping servers...${NC}"
    kill $(jobs -p) 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

if [ "$FRONTEND_ONLY" = true ]; then
    echo -e "${GREEN}Starting frontend only...${NC}"
    echo -e "  → http://localhost:5173"
    echo ""
    cd web && npm run dev
elif [ "$BACKEND_ONLY" = true ]; then
    echo -e "${GREEN}Starting backend only...${NC}"
    echo -e "  → http://localhost:8000"
    echo -e "  → http://localhost:8000/docs (API docs)"
    echo ""
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
else
    echo -e "${GREEN}Starting backend (API)...${NC}"
    echo -e "  → http://localhost:8000"
    echo -e "  → http://localhost:8000/docs (API docs)"
    echo ""

    # Start backend in background
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000 &
    BACKEND_PID=$!

    # Give backend a moment to start
    sleep 2

    echo ""
    echo -e "${GREEN}Starting frontend (Vite)...${NC}"
    echo -e "  → http://localhost:5173"
    echo ""

    # Start frontend in foreground
    cd web && npm run dev &
    FRONTEND_PID=$!

    echo ""
    echo -e "${CYAN}Press Ctrl+C to stop all servers${NC}"
    echo ""

    # Wait for both processes
    wait $BACKEND_PID $FRONTEND_PID
fi
