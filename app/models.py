"""SQLAlchemy ORM models.

These mirror migrations/001_schema.sql. The SQL file is the source of truth for
DDL (indexes, constraints); these classes exist for typed query construction.
We deliberately do NOT call metadata.create_all() in production -- the schema
is applied from the .sql file so the documented indexes are guaranteed present.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Facility(Base):
    __tablename__ = "facilities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[str] = mapped_column(String, nullable=False)

    sensors: Mapped[list["Sensor"]] = relationship(back_populates="facility")


class Sensor(Base):
    __tablename__ = "sensors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    facility_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    alert_threshold: Mapped[float] = mapped_column(Float, nullable=False)

    facility: Mapped["Facility"] = relationship(back_populates="sensors")

    __table_args__ = (
        CheckConstraint(
            "type IN ('flow', 'temperature', 'energy', 'pressure')",
            name="ck_sensors_type",
        ),
        Index("ix_sensors_facility_id", "facility_id"),
    )


class Reading(Base):
    __tablename__ = "readings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sensor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # Mirrors the composite index documented in 001_schema.sql.
        Index("ix_readings_sensor_recorded", "sensor_id", "recorded_at"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sensor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reading_value: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        CheckConstraint("severity IN ('low', 'medium', 'high')", name="ck_alerts_severity"),
        CheckConstraint("status IN ('active', 'resolved')", name="ck_alerts_status"),
        Index("ix_alerts_status", "status"),
        Index("ix_alerts_sensor_id", "sensor_id"),
    )
