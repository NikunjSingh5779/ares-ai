#!/usr/bin/env bash
# =============================================================================
# ARES AI — PostgreSQL Backup Script
# =============================================================================
# Usage:
#   ./backup.sh                  # Backup to default dir, keep 7 daily copies
#   BACKUP_DIR=/custom/path ./backup.sh
#   S3_BUCKET=s3://my-bucket ./backup.sh   # Also sync to S3
#
# Environment variables:
#   PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE  — DB connection
#   BACKUP_DIR      — Local backup directory (default: ./backups)
#   RETENTION_DAYS  — Days to keep local backups (default: 7)
#   S3_BUCKET       — S3 URL for remote sync (optional)
# =============================================================================
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
FILENAME="ares_ai_${TIMESTAMP}.sql.gz"
BACKUP_PATH="${BACKUP_DIR}/${FILENAME}"

# ── Ensure backup directory exists ─────────────────────────────────────────
mkdir -p "${BACKUP_DIR}"

# ── Dump database ──────────────────────────────────────────────────────────
echo "[$(date +%H:%M:%S)] Starting PostgreSQL backup: ${PGDATABASE:-ares_ai}"
pg_dump \
    --host="${PGHOST:-localhost}" \
    --port="${PGPORT:-5432}" \
    --username="${PGUSER:-ares}" \
    --dbname="${PGDATABASE:-ares_ai}" \
    --format=custom \
    --compress=6 \
    --verbose \
    --file="${BACKUP_PATH}" \
    2>&1 | tail -5

echo "[$(date +%H:%M:%S)] Backup written: ${BACKUP_PATH}"
BACKUP_SIZE=$(stat -c%s "${BACKUP_PATH}" 2>/dev/null || stat -f%z "${BACKUP_PATH}" 2>/dev/null || echo 0)
echo "[$(date +%H:%M:%S)] Backup size: ${BACKUP_SIZE} bytes"

# ── Rotate old backups ─────────────────────────────────────────────────────
echo "[$(date +%H:%M:%S)] Rotating backups older than ${RETENTION_DAYS} days"
find "${BACKUP_DIR}" -name "ares_ai_*.sql.gz" -type f -mtime "+${RETENTION_DAYS}" -delete

# ── Sync to S3 (optional) ─────────────────────────────────────────────────
if [ -n "${S3_BUCKET:-}" ]; then
    echo "[$(date +%H:%M:%S)] Syncing to S3: ${S3_BUCKET}"
    if command -v aws &>/dev/null; then
        aws s3 cp "${BACKUP_PATH}" "${S3_BUCKET}/"
        echo "[$(date +%H:%M:%S)] S3 sync complete"
    else
        echo "[WARN] AWS CLI not found — skipping S3 sync"
    fi
fi

echo "[$(date +%H:%M:%S)] Backup complete"
