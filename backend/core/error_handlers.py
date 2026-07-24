from fastapi import Request
from fastapi.responses import JSONResponse

from backend.core.exceptions import AresError, AuthenticationError, ConfigurationError, RateLimitError


async def ares_error_handler(request: Request, exc: AresError) -> JSONResponse:
    """Global exception handler for ARES AI domain errors."""
    status_code = 400
    if isinstance(exc, AuthenticationError):
        status_code = 401
    elif isinstance(exc, RateLimitError):
        status_code = 429
    elif isinstance(exc, ConfigurationError):
        status_code = 500

    return JSONResponse(
        status_code=status_code,
        content={"detail": str(exc), "error_type": exc.__class__.__name__},
    )


def setup_exception_handlers(app) -> None:
    """Register custom exception handlers with the FastAPI app."""
    app.add_exception_handler(AresError, ares_error_handler)
