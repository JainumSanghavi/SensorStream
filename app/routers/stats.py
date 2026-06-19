"""Time-bucketed aggregation -- the SQL showcase endpoint."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import NotFoundError
from app.models import Reading, Sensor
from app.schemas import StatBucket

router = APIRouter(prefix="/sensors", tags=["stats"])


@router.get("/{sensor_id}/stats", response_model=list[StatBucket])
async def sensor_stats(
    sensor_id: int,
    interval: str = Query("hour", pattern="^(hour|day)$"),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> list[StatBucket]:
    """Aggregate a sensor's readings into hourly or daily buckets.

    SQL strategy: date_trunc(interval, recorded_at) collapses each reading onto
    its bucket boundary; GROUP BY that bucket lets Postgres compute avg/min/max/
    count per bucket in a single pass. The WHERE on (sensor_id, recorded_at)
    rides the composite index so only the requested sensor+window is scanned --
    the aggregation never touches the rest of the table.
    """
    if await session.get(Sensor, sensor_id) is None:
        raise NotFoundError("sensor", sensor_id)

    bucket = func.date_trunc(interval, Reading.recorded_at).label("bucket")
    stmt = (
        select(
            bucket,
            func.avg(Reading.value).label("avg"),
            func.min(Reading.value).label("min"),
            func.max(Reading.value).label("max"),
            func.count().label("count"),
        )
        .where(Reading.sensor_id == sensor_id)
        .group_by(bucket)
        .order_by(bucket)
    )
    if from_ is not None:
        stmt = stmt.where(Reading.recorded_at >= from_)
    if to is not None:
        stmt = stmt.where(Reading.recorded_at <= to)

    rows = (await session.execute(stmt)).all()
    return [
        StatBucket(
            bucket=row.bucket,
            avg=float(row.avg),
            min=float(row.min),
            max=float(row.max),
            count=row.count,
        )
        for row in rows
    ]
