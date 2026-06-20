#!/usr/bin/env bash
# =============================================================================
# ARES AI — PostgreSQL Restore Script
# =============================================================================
# Usage:
#   ./restore.sh                           # Restore latest backup from default dir
#   ./restore.sh /path/to/backup.sql.gz    # Restore a specific file
#   BACKUP_DIR=/custom/path ./restore.sh   # Use custom backup dir
#
# WARNING: This will DROP and recreate the target database.
# =============================================================================
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-./backups}"

# ── Determine backup file ─────────────────────────────────────────────────
if [ $# -ge 1 ]; then
    BACKUP_FILE="$1"
else
    # Find the most recent backup
    BACKUP_FILE=$(find "${BACKUP_DIR}" -name "ares_ai_*.sql.gz" -type f -print0 \
        | xargs -0 ls -t 2>/dev/null | head -1)
fi

if [ -z "${BACKUP_FILE}" ] || [ ! -f "${BACKUP_FILE}" ]; then
    echo "ERROR: No backup file found in ${BACKUP_DIR}"
    echo "Usage: $0 [backup_file]"
    exit 1
fi

echo "[$(date +%H:%M:%S)] Restoring from: ${BACKUP_FILE}"

# ── Confirm ───────────────────────────────────────────────────────────────
echo ""
echo "WARNING: This will REPLACE the database ${PGDATABASE:-ares_ai}."
echo "Press Ctrl+C within 5 seconds to abort, or wait to continue..."
sleep 5

# ── Restore ───────────────────────────────────────────────────────────────
echo "[$(date +%H:%M:%S)] Dropping and recreating database..."
dropdb \
    --host="${PGHOST:-localhost}" \
    --port="${PGPORT:-5432}" \
    --username="${PGUSER:-ares}" \
    --if-exists \
    "${PGDATABASE:-ares_ai}"

createdb \
    --host="${PGHOST:-localhost}" \
    --port="${PGPORT:-5432}" \
    --username="${PGUSER:-ares}" \
    "${PGDATABASE:-ares_ai}"

echo "[$(date +%H:%M:%S)] Restoring data..."
pg_restore \
    --host="${PGHOST:-localhost}" \
    --port="${PGPORT:-5432}" \
    --username="${PGUSER:-ares}" \
    --dbname="${PGDATABASE:-ares_ai}" \
    --format=custom \
    --verbose \
    --clean \
    --if-exists \
    "${BACKUP_FILE}" \
    2>&1 | tail -10

echo "[$(date +%H:%M:%S)] Restore complete"
