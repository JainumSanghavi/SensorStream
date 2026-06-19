"""In-process counters for the /metrics endpoint.

These are intentionally simple module-level counters (single-process). The
README's "at scale" section explains why a real deployment would push these to
Prometheus / StatsD instead of holding them in app memory. They survive only
the process lifetime and reset on restart -- totals that must be durable are
read from the DB instead (see routers/health.py).
"""
import time
from collections import deque
from threading import Lock

_lock = Lock()

# Monotonic counter: readings ingested since process start.
_readings_ingested = 0
# Monotonic counter: alerts triggered since process start.
_alerts_triggered = 0

# Sliding window of (timestamp, count) for ingestion-rate estimation.
_RATE_WINDOW_SECONDS = 60
_ingest_events: deque[tuple[float, int]] = deque()


def record_ingest(readings: int, alerts: int, *, now: float | None = None) -> None:
    global _readings_ingested, _alerts_triggered
    ts = now if now is not None else time.monotonic()
    with _lock:
        _readings_ingested += readings
        _alerts_triggered += alerts
        _ingest_events.append((ts, readings))


def _ingestion_rate_per_sec(now: float) -> float:
    cutoff = now - _RATE_WINDOW_SECONDS
    with _lock:
        while _ingest_events and _ingest_events[0][0] < cutoff:
            _ingest_events.popleft()
        total = sum(count for _, count in _ingest_events)
    return round(total / _RATE_WINDOW_SECONDS, 2)


def snapshot(*, now: float | None = None) -> dict[str, float | int]:
    ts = now if now is not None else time.monotonic()
    with _lock:
        readings = _readings_ingested
        alerts = _alerts_triggered
    return {
        "readingsIngestedSinceStart": readings,
        "alertsTriggeredSinceStart": alerts,
        "ingestionRatePerSec": _ingestion_rate_per_sec(ts),
    }
