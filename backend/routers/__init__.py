"""API routers — organized by domain.

Aggregates all routers for inclusion in the main FastAPI app.
"""

from backend.routers.analysis import router as analysis_router
from backend.routers.trading import router as trading_router
from backend.routers.journal import router as journal_router
from backend.routers.agents import router as agents_router
from backend.routers.monitoring import router as monitoring_router
from backend.routers.live import router as live_router

__all__ = [
    "analysis_router",
    "trading_router",
    "journal_router",
    "agents_router",
    "monitoring_router",
    "live_router",
]
