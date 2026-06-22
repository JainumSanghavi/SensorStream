"""Sensor CRUD + the readings ingestion and query endpoints."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import metrics
from app.auth import require_api_key
from app.config import get_settings
from app.db import get_session
from app.errors import AppError, NotFoundError
from app.models import Reading, Sensor
from app.pagination import decode_cursor, encode_cursor
from app.schemas import (
    CursorPage,
    CursorPagination,
    IngestSummary,
    OffsetPagination,
    Page,
    ReadingBatchIn,
    ReadingOut,
    SensorOut,
    SensorUpdate,
)
from app.services import ingest_readings

router = APIRouter(prefix="/sensors", tags=["sensors"])
settings = get_settings()


async def _get_sensor_or_404(session: AsyncSession, sensor_id: int) -> Sensor:
    sensor = await session.get(Sensor, sensor_id)
    if sensor is None:
        raise NotFoundError("sensor", sensor_id)
    return sensor


# --------------------------------------------------------------------------- #
# Query: list / get / patch / delete
# --------------------------------------------------------------------------- #
@router.get("", response_model=Page[SensorOut])
async def list_sensors(
    page: int = Query(1, ge=1),
    page_size: int = Query(
        settings.default_page_size, ge=1, le=settings.max_page_size, alias="pageSize"
    ),
    session: AsyncSession = Depends(get_session),
) -> Page[SensorOut]:
    """List sensors with OFFSET pagination.

    OFFSET is fine here: the sensor table is small and bounded, so the deep-page
    cost that motivates keyset pagination on readings simply doesn't apply.
    """
    total = await session.scalar(select(func.count()).select_from(Sensor))
    rows = (
        await session.scalars(
            select(Sensor)
            .order_by(Sensor.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return Page[SensorOut](
        data=[SensorOut.model_validate(r) for r in rows],
        pagination=OffsetPagination(page=page, page_size=page_size, total=total or 0),
    )


@router.get("/{sensor_id}", response_model=SensorOut)
async def get_sensor(
    sensor_id: int, session: AsyncSession = Depends(get_session)
) -> SensorOut:
    sensor = await _get_sensor_or_404(session, sensor_id)
    return SensorOut.model_validate(sensor)


@router.patch(
    "/{sensor_id}",
    response_model=SensorOut,
    dependencies=[Depends(require_api_key)],
)
async def patch_sensor(
    sensor_id: int,
    payload: SensorUpdate,
    session: AsyncSession = Depends(get_session),
) -> SensorOut:
    sensor = await _get_sensor_or_404(session, sensor_id)
    updates = payload.updates()
    if not updates:
        raise AppError(
            code="empty_update",
            message="No updatable fields were provided",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    await session.execute(
        update(Sensor).where(Sensor.id == sensor_id).values(**updates)
    )
    await session.commit()
    await session.refresh(sensor)
    return SensorOut.model_validate(sensor)


@router.delete(
    "/{sensor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_key)],
)
async def delete_sensor(
    sensor_id: int, session: AsyncSession = Depends(get_session)
) -> Response:
    await _get_sensor_or_404(session, sensor_id)
    await session.execute(sql_delete(Sensor).where(Sensor.id == sensor_id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Ingestion: batch insert + alert generation
# --------------------------------------------------------------------------- #
@router.post(
    "/{sensor_id}/readings",
    status_code=status.HTTP_201_CREATED,
    response_model=IngestSummary,
    dependencies=[Depends(require_api_key)],
)
async def ingest(
    sensor_id: int,
    batch: ReadingBatchIn,
    session: AsyncSession = Depends(get_session),
) -> IngestSummary:
    """Accept a BATCH of readings, bulk-insert them, and fire alerts on breach."""
    if len(batch.readings) > settings.max_batch_size:
        raise AppError(
            code="batch_too_large",
            message=f"Batch exceeds max size of {settings.max_batch_size}",
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            details={"received": len(batch.readings), "max": settings.max_batch_size},
        )

    sensor = await _get_sensor_or_404(session, sensor_id)
    ingested, alerts = await ingest_readings(
        session, sensor_id, sensor.alert_threshold, batch.readings
    )
    metrics.record_ingest(ingested, alerts)
    return IngestSummary(sensor_id=sensor_id, ingested=ingested, alerts_triggered=alerts)


# --------------------------------------------------------------------------- #
# Query: readings with keyset (cursor) pagination
# --------------------------------------------------------------------------- #
@router.get("/{sensor_id}/readings", response_model=CursorPage[ReadingOut])
async def list_readings(
    sensor_id: int,
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    limit: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
    cursor: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> CursorPage[ReadingOut]:
    """Readings for a sensor, newest first, via keyset pagination.

    Ordering is (recorded_at DESC, id DESC). The cursor carries the last seen
    (recorded_at, id); the next page asks for rows strictly "before" it. This
    rides the composite index ix_readings_sensor_recorded and stays
    constant-time regardless of how deep the client pages -- see pagination.py.
    """
    await _get_sensor_or_404(session, sensor_id)

    stmt = select(Reading).where(Reading.sensor_id == sensor_id)
    if from_ is not None:
        stmt = stmt.where(Reading.recorded_at >= from_)
    if to is not None:
        stmt = stmt.where(Reading.recorded_at <= to)

    if cursor is not None:
        c_recorded_at, c_id = decode_cursor(cursor)
        # Row-value comparison = the keyset predicate. "Earlier than the cursor"
        # means an older timestamp, OR same timestamp with a smaller id.
        stmt = stmt.where(
            (Reading.recorded_at < c_recorded_at)
            | ((Reading.recorded_at == c_recorded_at) & (Reading.id < c_id))
        )

    stmt = stmt.order_by(Reading.recorded_at.desc(), Reading.id.desc())
    # Fetch one extra row to detect whether a further page exists.
    rows = (await session.scalars(stmt.limit(limit + 1))).all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = (
        encode_cursor(page_rows[-1].recorded_at, page_rows[-1].id)
        if has_more and page_rows
        else None
    )

    return CursorPage[ReadingOut](
        data=[ReadingOut.model_validate(r) for r in page_rows],
        pagination=CursorPagination(
            limit=limit, next_cursor=next_cursor, has_more=has_more
        ),
    )
