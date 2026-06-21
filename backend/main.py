"""ARES AI — FastAPI Application Entry Point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from backend.core.logging import setup_logging
from backend.core.metrics import MetricsMiddleware
from backend.core.rate_limit import RateLimitMiddleware
from backend.core.security import SecurityHeadersMiddleware
from backend.routers import (
    agents_router,
    analysis_router,
    journal_router,
    live_router,
    monitoring_router,
    trading_router,
)
from configs.settings import settings

logger = logging.getLogger("ares")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    # ── Startup ───────────────────────────────────────────────────
    logger.info(
        "ARES AI starting",
        extra={
            "api_host": settings.api_host,
            "api_port": settings.api_port,
            "debug": settings.api_debug,
        },
    )
    yield
    # ── Shutdown ──────────────────────────────────────────────────
    logger.info("ARES AI shutting down")


# ── Application instance ────────────────────────────────────────────────

app = FastAPI(
    title="ARES AI API",
    description="Autonomous Research Execution System — Multi-Agent Trading Platform",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Logging configuration ──────────────────────────────────────────────

setup_logging(level=settings.log_level.upper())

# ── Middleware (order matters: outermost first) ────────────────────────

# 1. CORS — must be early to handle preflight
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Security headers — apply to every response (after CORS for proper header order)
app.add_middleware(SecurityHeadersMiddleware)

# 3. Rate limiting — per-endpoint token bucket
app.add_middleware(RateLimitMiddleware, default_limit=settings.api_rate_limit_per_minute)

# 4. Prometheus metrics — records request count, duration, status
app.add_middleware(MetricsMiddleware)

# ── Domain routers ─────────────────────────────────────────────────────

app.include_router(analysis_router)
app.include_router(trading_router)
app.include_router(journal_router)
app.include_router(agents_router)
app.include_router(monitoring_router)
app.include_router(live_router)

# ── Prometheus /metrics endpoint (ASGI mount) ─────────────────────────

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# ── Health & Info Endpoints ────────────────────────────────────────────


@app.get("/health", tags=["system"])
async def health_check():
    """Enhanced health check. Reports reachability of DB, Redis, and ChromaDB."""
    from database.connection import check_connection as check_db

    db_ok = await check_db()
    redis_ok = await _check_redis()
    chroma_ok = await _check_chromadb()

    all_ok = db_ok and redis_ok and chroma_ok

    return {
        "status": "ok" if all_ok else "degraded",
        "version": "0.1.0",
        "service": "ares-ai",
        "checks": {
            "database": "ok" if db_ok else "unreachable",
            "redis": "ok" if redis_ok else "unreachable",
            "chromadb": "ok" if chroma_ok else "unreachable",
        },
    }


@app.get("/", tags=["system"])
async def root():
    """Root endpoint — API information."""
    return {
        "service": "ARES AI",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }


# ── Health check helpers ──────────────────────────────────────────────


async def _check_redis() -> bool:
    """Check Redis reachability with a short timeout."""
    try:
        import redis.asyncio as aioredis

        r = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            db=settings.redis_db,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        result = await asyncio.wait_for(r.ping(), timeout=3)
        await r.aclose()
        return result
    except Exception:
        return False


async def _check_chromadb() -> bool:
    """Check ChromaDB reachability with a short timeout."""
    try:
        import chromadb

        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )
        await asyncio.wait_for(
            asyncio.to_thread(client.heartbeat), timeout=3
        )
        return True
    except Exception:
        return False
