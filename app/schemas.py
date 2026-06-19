"""Pydantic v2 request/response models.

Conventions enforced here:
- camelCase JSON field names (alias_generator) while keeping snake_case in Python.
- populate_by_name so handlers can construct models with snake_case kwargs.
- All timestamps are timezone-aware datetimes serialised as ISO 8601 UTC.
"""
from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

SensorType = Literal["flow", "temperature", "energy", "pressure"]
Severity = Literal["low", "medium", "high"]
AlertStatus = Literal["active", "resolved"]


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# --------------------------------------------------------------------------- #
# Sensors
# --------------------------------------------------------------------------- #
class SensorOut(CamelModel):
    id: int
    facility_id: int
    name: str
    type: SensorType
    alert_threshold: float


class SensorUpdate(CamelModel):
    """Partial update -- every field optional; only provided fields change."""

    name: str | None = None
    type: SensorType | None = None
    alert_threshold: float | None = None

    def updates(self) -> dict:
        # exclude_unset distinguishes "field omitted" from "field set to null".
        return self.model_dump(exclude_unset=True)


# --------------------------------------------------------------------------- #
# Readings / ingestion
# --------------------------------------------------------------------------- #
class ReadingIn(CamelModel):
    value: float
    recorded_at: datetime


class ReadingBatchIn(CamelModel):
    # min_length=1 → an empty batch is a 422, not a silent no-op.
    readings: Annotated[list[ReadingIn], Field(min_length=1)]


class ReadingOut(CamelModel):
    id: int
    sensor_id: int
    value: float
    recorded_at: datetime


class IngestSummary(CamelModel):
    sensor_id: int
    ingested: int
    alerts_triggered: int


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
class AlertOut(CamelModel):
    id: int
    sensor_id: int
    severity: Severity
    status: AlertStatus
    triggered_at: datetime
    reading_value: float


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
class StatBucket(CamelModel):
    bucket: datetime
    avg: float
    min: float
    max: float
    count: int


# --------------------------------------------------------------------------- #
# Pagination envelopes
# --------------------------------------------------------------------------- #
T = TypeVar("T")


class OffsetPagination(CamelModel):
    page: int
    page_size: int
    total: int


class CursorPagination(CamelModel):
    limit: int
    # base64 cursor for the NEXT page; null when no further rows exist.
    next_cursor: str | None = None
    has_more: bool


class Page(CamelModel, Generic[T]):
    data: list[T]
    pagination: OffsetPagination


class CursorPage(CamelModel, Generic[T]):
    data: list[T]
    pagination: CursorPagination
