"""Health check and metrics-style counters."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import metrics
from app.db import get_session
from app.models import Alert, Reading

router = APIRouter(tags=["ops"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    """Liveness + DB connectivity check."""
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # pragma: no cover - only on real DB outage
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}


@router.get("/metrics")
async def metrics_endpoint(session: AsyncSession = Depends(get_session)) -> dict:
    """Basic operational counters.

    Process-lifetime counters (ingestion rate, since-start totals) come from the
    in-memory metrics module; durable totals (total readings, active alerts)
    are read from the DB so they're correct across restarts.
    """
    total_readings = await session.scalar(select(func.count()).select_from(Reading))
    active_alerts = await session.scalar(
        select(func.count()).select_from(Alert).where(Alert.status == "active")
    )
    snap = metrics.snapshot()
    return {
        "totalReadings": total_readings or 0,
        "activeAlerts": active_alerts or 0,
        **snap,
    }
