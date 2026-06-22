"""FastAPI application factory and wiring."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import engine
from app.errors import register_exception_handlers
from app.logging_config import configure_logging, request_logging_middleware
from app.routers import alerts, health, sensors, stats

logger = logging.getLogger("sensorstream")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup checks + graceful shutdown."""
    settings = get_settings()
    if settings.api_key is None:
        logger.warning(
            "API_KEY is not set -- write endpoints are UNAUTHENTICATED. "
            "Set API_KEY to require an X-API-Key header on mutating requests."
        )
    yield
    # Release pooled DB connections cleanly so shutdown doesn't drop them mid-flight.
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="SensorStream",
        description="Real-time industrial sensor ingestion & alerting backend.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Structured request logging for every request.
    app.middleware("http")(request_logging_middleware)

    # Shared error envelope for AppError / HTTPException / validation errors.
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(sensors.router)
    app.include_router(stats.router)
    app.include_router(alerts.router)
    return app


app = create_app()
