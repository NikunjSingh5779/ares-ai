# =============================================================================
# ARES AI — Backend Dockerfile (multi-stage)
# =============================================================================

# ---- Build Stage ----
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system build deps (needed by some pip packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps (layer is cached as long as pyproject.toml is unchanged)
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# ---- Runtime Stage ----
FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Copy virtualenv from builder (all deps + project installed as package)
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY backend/ ./backend/
COPY configs/ ./configs/
COPY database/ ./database/
COPY agents/ ./agents/
COPY paper_trading/ ./paper_trading/
COPY live_trading/ ./live_trading/
COPY backtesting/ ./backtesting/
COPY scripts/ ./scripts/
COPY migrations/ ./migrations/
COPY alembic.ini ./alembic.ini
COPY pyproject.toml ./pyproject.toml

# Copy entrypoint
COPY docker/backend-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import http.client; conn=http.client.HTTPConnection('localhost:8000'); conn.request('GET','/health'); resp=conn.getresponse(); exit(0) if resp.status==200 else exit(1)"

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
