"""Alert query endpoint."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import Alert
from app.schemas import AlertOut, AlertStatus, OffsetPagination, Page

router = APIRouter(prefix="/alerts", tags=["alerts"])
settings = get_settings()


@router.get("", response_model=Page[AlertOut])
async def list_alerts(
    status: AlertStatus | None = Query(None),
    sensor_id: int | None = Query(None, alias="sensorId"),
    page: int = Query(1, ge=1),
    page_size: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
    session: AsyncSession = Depends(get_session),
) -> Page[AlertOut]:
    """List alerts, optionally filtered by status (rides ix_alerts_status)."""
    filters = []
    if status is not None:
        filters.append(Alert.status == status)
    if sensor_id is not None:
        filters.append(Alert.sensor_id == sensor_id)

    total = await session.scalar(
        select(func.count()).select_from(Alert).where(*filters)
    )
    rows = (
        await session.scalars(
            select(Alert)
            .where(*filters)
            .order_by(Alert.triggered_at.desc(), Alert.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return Page[AlertOut](
        data=[AlertOut.model_validate(r) for r in rows],
        pagination=OffsetPagination(page=page, page_size=page_size, total=total or 0),
    )
