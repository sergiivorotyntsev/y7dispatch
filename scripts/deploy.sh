#!/bin/bash
# deploy.sh — Pull latest code, rebuild, and restart
#
# Usage: ./scripts/deploy.sh
#
# Steps:
#   1. Backup current DB
#   2. Pull latest code from GitHub
#   3. Rebuild frontend
#   4. Rebuild and restart Docker container
#   5. Health check

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== y7dispatch deploy ==="
echo "Project: $PROJECT_DIR"
cd "$PROJECT_DIR"

# 1. Pre-deploy backup
echo ""
echo "--- Step 1: Pre-deploy backup ---"
./scripts/backup.sh backups/pre-deploy 2>/dev/null || echo "  Backup skipped (non-critical)"

# 2. Pull latest code
echo ""
echo "--- Step 2: Pull latest code ---"
git pull origin main

# 3. Rebuild frontend
echo ""
echo "--- Step 3: Build frontend ---"
cd web && npm install --production=false && npm run build && cd ..

# 4. Rebuild and restart container
echo ""
echo "--- Step 4: Docker rebuild + restart ---"
docker compose down
docker compose build --no-cache
docker compose up -d

# 5. Health check (wait up to 30s)
echo ""
echo "--- Step 5: Health check ---"
for i in $(seq 1 6); do
    sleep 5
    if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "  Health check passed!"
        echo "=== Deploy complete ==="
        exit 0
    fi
    echo "  Waiting... ($((i*5))s)"
done

echo "  WARNING: Health check failed after 30s"
echo "  Check logs: docker compose logs app"
exit 1
