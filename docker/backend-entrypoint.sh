#!/bin/sh
# =============================================================================
# ARES AI — Backend Entrypoint
# Runs database migrations, then starts the FastAPI server.
# =============================================================================

set -e

echo "→ Running Alembic migrations..."

# init.sql runs on a fresh PostgreSQL volume and creates the current schema.
# In that case Alembic only needs a version row: stamp 0001, then let the later
# revisions (which are idempotent) bring the version table to head.
if python - <<'PY'
import asyncio

from sqlalchemy import text

from database.connection import engine


async def initialized_by_init_sql() -> bool:
    async with engine.connect() as conn:
        has_users = await conn.scalar(text("SELECT to_regclass('public.users') IS NOT NULL"))
        has_version_table = await conn.scalar(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        )
        version = None
        if has_version_table:
            version = await conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    await engine.dispose()
    return bool(has_users and not version)


raise SystemExit(0 if asyncio.run(initialized_by_init_sql()) else 1)
PY
then
    echo "→ Detected schema created by init.sql; stamping 0001"
    alembic stamp 0001
fi

alembic upgrade head
echo "→ Migrations complete."

echo "→ Starting uvicorn on ${API_HOST:-0.0.0.0}:${API_PORT:-8000}..."
exec uvicorn backend.main:app \
    --host "${API_HOST:-0.0.0.0}" \
    --port "${API_PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips '*'
