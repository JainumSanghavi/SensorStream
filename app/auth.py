"""API-key authentication for the mutating endpoints.

A single static key in `API_KEY` gates the write endpoints (ingest, patch,
delete). It is intentionally simple -- a production deployment would issue
per-client keys or JWTs (see the README's "at scale" notes) -- but it closes the
"anyone can DELETE a sensor" gap and demonstrates the dependency pattern.

When no key is configured the dependency lets requests through (and `main.py`
logs a warning at startup), keeping local development and the test suite
frictionless. Settings arrive via Depends(get_settings) so tests can override
the dependency to exercise both the authenticated and unauthenticated paths.
"""
from fastapi import Depends, Header, status

from app.config import Settings, get_settings
from app.errors import AppError


async def require_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    """Reject the request unless a configured API key matches the header.

    No-op when `api_key` is unset (auth disabled).
    """
    expected = settings.api_key
    if expected is None:
        return
    if x_api_key != expected:
        raise AppError(
            code="unauthorized",
            message="Missing or invalid API key",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
