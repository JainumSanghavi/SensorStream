"""Generate realistic synthetic telemetry and bulk-load it via Postgres COPY.

The signal model per reading is:
    value = baseline + amplitude * sin(daily_phase) + gaussian_noise
with ~0.5% of readings replaced by a SPIKE that is pushed past the sensor's
alert_threshold (so the alerting path has realistic, sparse positives).

Loading uses asyncpg's COPY (copy_records_to_table) -- a single streamed binary
load per sensor -- NOT row-by-row INSERTs. COPY is the fastest way to get bulk
data into Postgres; millions of INSERT statements would be orders of magnitude
slower (per-statement parse/plan/round-trip overhead).

Usage:
    python -m scripts.seed --readings 3000000
    python -m scripts.seed --readings 50000 --days 7 --reset

All data is SYNTHETIC -- generated purely to exercise query performance at
realistic volume.
"""
import argparse
import asyncio
import math
import random
from datetime import datetime, timedelta, timezone

import asyncpg

from app.config import get_settings

# Per-type signal profiles. threshold is chosen a few sigma above the normal
# envelope so only spikes (and rare noise) breach it.
PROFILES = {
    "flow":        {"baseline": 100.0, "amplitude": 20.0, "noise": 5.0,  "threshold": 150.0, "unit": "L/s"},
    "temperature": {"baseline": 60.0,  "amplitude": 10.0, "noise": 2.0,  "threshold": 85.0,  "unit": "C"},
    "energy":      {"baseline": 500.0, "amplitude": 100.0,"noise": 30.0, "threshold": 750.0, "unit": "kW"},
    "pressure":    {"baseline": 30.0,  "amplitude": 5.0,  "noise": 1.5,  "threshold": 45.0,  "unit": "bar"},
}

REGIONS = ["us-east", "us-west", "eu-central", "ap-south"]
SPIKE_RATE = 0.005  # ~0.5% of readings spike past threshold


def _value(profile: dict, ts: datetime, *, spike: bool) -> float:
    # Daily sine cycle: one full period every 24h, peaking mid-afternoon.
    seconds_into_day = ts.hour * 3600 + ts.minute * 60 + ts.second
    phase = 2 * math.pi * seconds_into_day / 86400.0
    base = profile["baseline"] + profile["amplitude"] * math.sin(phase)
    val = base + random.gauss(0, profile["noise"])
    if spike:
        # Push clearly past threshold: between 1.05x and 1.6x of it.
        val = profile["threshold"] * random.uniform(1.05, 1.60)
    return round(val, 4)


def _severity(value: float, threshold: float) -> str:
    ratio = (abs(value) - abs(threshold)) / abs(threshold)
    if ratio >= 0.5:
        return "high"
    if ratio >= 0.25:
        return "medium"
    return "low"


async def _reset(conn: asyncpg.Connection) -> None:
    # TRUNCATE ... RESTART IDENTITY CASCADE clears everything and resets ids.
    await conn.execute(
        "TRUNCATE alerts, readings, sensors, facilities RESTART IDENTITY CASCADE"
    )


async def seed(total_readings: int, days: int, facilities: int, reset: bool) -> None:
    settings = get_settings()
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    try:
        if reset:
            await _reset(conn)
            print("[seed] truncated existing data")

        # --- facilities + sensors ------------------------------------------
        sensor_specs: list[tuple[int, str, float]] = []  # (id, type, threshold)
        for f in range(facilities):
            region = REGIONS[f % len(REGIONS)]
            fac_id = await conn.fetchval(
                "INSERT INTO facilities (name, region) VALUES ($1, $2) RETURNING id",
                f"Facility {f + 1}",
                region,
            )
            # One sensor of every type per facility.
            for stype, prof in PROFILES.items():
                sid = await conn.fetchval(
                    """INSERT INTO sensors (facility_id, name, type, alert_threshold)
                       VALUES ($1, $2, $3, $4) RETURNING id""",
                    fac_id,
                    f"{stype}-{f + 1}",
                    stype,
                    prof["threshold"],
                )
                sensor_specs.append((sid, stype, prof["threshold"]))

        n_sensors = len(sensor_specs)
        per_sensor = max(1, total_readings // n_sensors)
        # Even cadence across the window so date_trunc buckets are well-populated.
        window = timedelta(days=days)
        step = window / per_sensor
        start = datetime.now(timezone.utc) - window

        print(
            f"[seed] {facilities} facilities, {n_sensors} sensors, "
            f"~{per_sensor:,} readings/sensor over {days}d "
            f"(~{per_sensor * n_sensors:,} total)"
        )

        total_alerts = 0
        for sid, stype, threshold in sensor_specs:
            profile = PROFILES[stype]
            reading_records: list[tuple] = []
            alert_records: list[tuple] = []
            ts = start
            for _ in range(per_sensor):
                spike = random.random() < SPIKE_RATE
                val = _value(profile, ts, spike=spike)
                reading_records.append((sid, val, ts))
                if abs(val) > abs(threshold):
                    alert_records.append(
                        (sid, _severity(val, threshold), "active", ts, val)
                    )
                ts += step

            await conn.copy_records_to_table(
                "readings",
                records=reading_records,
                columns=["sensor_id", "value", "recorded_at"],
            )
            if alert_records:
                await conn.copy_records_to_table(
                    "alerts",
                    records=alert_records,
                    columns=["sensor_id", "severity", "status", "triggered_at", "reading_value"],
                )
                total_alerts += len(alert_records)
            print(f"  sensor {sid:>3} ({stype:<11}) loaded {per_sensor:,} readings, "
                  f"{len(alert_records):,} alerts")

        # Keep the planner's statistics fresh after a big bulk load.
        await conn.execute("ANALYZE readings")
        await conn.execute("ANALYZE alerts")
        print(f"[seed] done: ~{per_sensor * n_sensors:,} readings, {total_alerts:,} alerts")
    finally:
        await conn.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Seed synthetic sensor telemetry.")
    p.add_argument("--readings", type=int, default=3_000_000, help="total readings (approx)")
    p.add_argument("--days", type=int, default=30, help="time window to spread readings over")
    p.add_argument("--facilities", type=int, default=3, help="number of facilities")
    p.add_argument("--reset", action="store_true", help="truncate existing data first")
    args = p.parse_args()
    asyncio.run(seed(args.readings, args.days, args.facilities, args.reset))


if __name__ == "__main__":
    main()
