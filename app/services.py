"""Domain logic shared by routers (kept thin and testable)."""
from datetime import datetime, timezone

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, Reading
from app.schemas import ReadingIn


def classify_severity(value: float, threshold: float) -> str:
    """Map a threshold breach to low/medium/high by how far it overshoots.

    Severity scales with the overshoot ratio so a small exceedance is 'low'
    while a large one is 'high'. Uses magnitudes so it behaves for any sign of
    threshold/value.
    """
    overshoot = abs(value) - abs(threshold)
    margin = abs(threshold) if threshold != 0 else 1.0
    ratio = overshoot / margin
    if ratio >= 0.5:
        return "high"
    if ratio >= 0.25:
        return "medium"
    return "low"


def _to_utc(dt: datetime) -> datetime:
    """Normalise to timezone-aware UTC (naive input is assumed UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def ingest_readings(
    session: AsyncSession,
    sensor_id: int,
    threshold: float,
    readings: list[ReadingIn],
) -> tuple[int, int]:
    """Bulk-insert a batch of readings and any triggered alerts.

    Returns (ingested_count, alerts_triggered). Both inserts are SET-BASED:
    one multi-row INSERT for readings, one for alerts -- never a per-row loop.
    Runs in a single transaction so a failure leaves no partial batch.
    """
    reading_rows = [
        {
            "sensor_id": sensor_id,
            "value": r.value,
            "recorded_at": _to_utc(r.recorded_at),
        }
        for r in readings
    ]

    # Alerts are derived in Python from the same batch (cheap, in-memory) so we
    # don't re-read the rows we just wrote.
    alert_rows = [
        {
            "sensor_id": sensor_id,
            "severity": classify_severity(r.value, threshold),
            "status": "active",
            "triggered_at": _to_utc(r.recorded_at),
            "reading_value": r.value,
        }
        for r in readings
        if abs(r.value) > abs(threshold)
    ]

    async with session.begin():
        await session.execute(insert(Reading), reading_rows)
        if alert_rows:
            await session.execute(insert(Alert), alert_rows)

    return len(reading_rows), len(alert_rows)
