#!/bin/bash
# backup.sh — Backup DB + config, rotate last 30 days
#
# Usage: ./scripts/backup.sh [backup_dir]
#   backup_dir: where to store backups (default: ./backups)
#
# Creates timestamped backups of:
#   - data/control_panel.db (SQLite database)
#   - config/ directory (poll settings, etc.)
#   - warehouses.yaml, cd_defaults.yaml
#
# Rotates: keeps last 30 backups, deletes older ones.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${1:-$PROJECT_DIR/backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_NAME="backup_${TIMESTAMP}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"

echo "=== y7dispatch backup ==="
echo "Project: $PROJECT_DIR"
echo "Backup:  $BACKUP_PATH"

mkdir -p "$BACKUP_PATH"

# Database (use SQLite online backup for safety)
DB_PATH="$PROJECT_DIR/data/control_panel.db"
if [ -f "$DB_PATH" ]; then
    sqlite3 "$DB_PATH" ".backup '$BACKUP_PATH/control_panel.db'" 2>/dev/null || \
        cp "$DB_PATH" "$BACKUP_PATH/control_panel.db"
    echo "  DB: $(du -h "$BACKUP_PATH/control_panel.db" | cut -f1)"
else
    echo "  DB: not found (skipped)"
fi

# Config directory
if [ -d "$PROJECT_DIR/config" ]; then
    cp -r "$PROJECT_DIR/config" "$BACKUP_PATH/config"
    echo "  Config: copied"
fi

# YAML configs
for f in warehouses.yaml cd_defaults.yaml cd_field_mapping.yaml cd_field_mapping_v2.yaml pricing_config.yaml; do
    if [ -f "$PROJECT_DIR/$f" ]; then
        cp "$PROJECT_DIR/$f" "$BACKUP_PATH/$f"
    fi
done
echo "  YAML configs: copied"

# Compress
tar -czf "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" -C "$BACKUP_DIR" "$BACKUP_NAME"
rm -rf "$BACKUP_PATH"
echo "  Archive: ${BACKUP_NAME}.tar.gz ($(du -h "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" | cut -f1))"

# Rotate — keep last 30
BACKUPS=($(ls -1t "$BACKUP_DIR"/backup_*.tar.gz 2>/dev/null))
if [ ${#BACKUPS[@]} -gt 30 ]; then
    for old in "${BACKUPS[@]:30}"; do
        rm -f "$old"
        echo "  Rotated: $(basename "$old")"
    done
fi

echo "=== Done ==="
