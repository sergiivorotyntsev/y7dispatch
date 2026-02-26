#!/bin/bash
# restore.sh — Restore DB from backup
#
# Usage: ./scripts/restore.sh <backup_archive.tar.gz>
#
# Restores:
#   - data/control_panel.db from backup
#   - config/ directory from backup
#   - YAML configs from backup

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <backup_archive.tar.gz>"
    echo ""
    echo "Available backups:"
    ls -1t backups/backup_*.tar.gz 2>/dev/null || echo "  No backups found in ./backups/"
    exit 1
fi

ARCHIVE="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TEMP_DIR=$(mktemp -d)

echo "=== y7dispatch restore ==="
echo "Archive: $ARCHIVE"
echo "Project: $PROJECT_DIR"

# Extract backup
echo ""
echo "--- Extracting backup ---"
tar -xzf "$ARCHIVE" -C "$TEMP_DIR"
BACKUP_DIR=$(ls "$TEMP_DIR")
BACKUP_PATH="$TEMP_DIR/$BACKUP_DIR"

echo "  Contents: $(ls "$BACKUP_PATH")"

# Stop app if running
echo ""
echo "--- Stopping app ---"
cd "$PROJECT_DIR"
docker compose down 2>/dev/null || true

# Restore DB
if [ -f "$BACKUP_PATH/control_panel.db" ]; then
    echo ""
    echo "--- Restoring database ---"
    cp "$PROJECT_DIR/data/control_panel.db" "$PROJECT_DIR/data/control_panel.db.pre-restore" 2>/dev/null || true
    cp "$BACKUP_PATH/control_panel.db" "$PROJECT_DIR/data/control_panel.db"
    echo "  DB restored (previous saved as .pre-restore)"
fi

# Restore config
if [ -d "$BACKUP_PATH/config" ]; then
    echo ""
    echo "--- Restoring config ---"
    cp -r "$BACKUP_PATH/config/"* "$PROJECT_DIR/config/" 2>/dev/null || true
    echo "  Config restored"
fi

# Restore YAML configs
for f in warehouses.yaml cd_defaults.yaml cd_field_mapping.yaml cd_field_mapping_v2.yaml pricing_config.yaml; do
    if [ -f "$BACKUP_PATH/$f" ]; then
        cp "$BACKUP_PATH/$f" "$PROJECT_DIR/$f"
    fi
done
echo "  YAML configs restored"

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
echo "--- Restart app ---"
docker compose up -d

echo ""
echo "=== Restore complete ==="
echo "Verify: curl http://localhost:8000/api/health"
