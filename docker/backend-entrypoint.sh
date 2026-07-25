#!/bin/sh
# =============================================================================
# ARES AI — Backend Entrypoint
# Runs database migrations, then starts the FastAPI server.
# =============================================================================

set -e

echo "→ Running Alembic migrations..."
alembic upgrade head
echo "→ Migrations complete."

echo "→ Starting uvicorn on ${API_HOST:-0.0.0.0}:${API_PORT:-8000}..."
exec uvicorn backend.main:app \
    --host "${API_HOST:-0.0.0.0}" \
    --port "${API_PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips '*'
