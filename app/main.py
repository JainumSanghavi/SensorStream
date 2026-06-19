"""FastAPI application factory and wiring."""
from fastapi import FastAPI

from app.config import get_settings
from app.errors import register_exception_handlers
from app.logging_config import configure_logging, request_logging_middleware
from app.routers import alerts, health, sensors, stats


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="SensorStream",
        description="Real-time industrial sensor ingestion & alerting backend.",
        version="1.0.0",
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
