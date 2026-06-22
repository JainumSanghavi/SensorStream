"""Application metrics.

Two layers live here:

1. **Prometheus instruments** (Counter/Histogram on the default registry) --
   the durable, scrape-based metrics a real deployment runs on. HTTP-level
   metrics (request rate, latency histograms) are added automatically by the
   instrumentator in app/observability.py; the business metrics below
   (readings ingested, alerts fired, batch sizes) are domain-specific so we
   declare them explicitly and increment them from the ingest path.

2. **In-process counters** -- the lightweight numbers behind the human-readable
   /metrics/summary JSON. They survive only the process lifetime; durable
   totals (total readings, active alerts) are read from the DB instead.
"""
import time
from collections import deque
from threading import Lock

from prometheus_client import Counter, Histogram

# --------------------------------------------------------------------------- #
# Prometheus instruments (exposed at /metrics in text format -- see
# observability.py). On the default registry so the instrumentator renders them.
# --------------------------------------------------------------------------- #
READINGS_INGESTED = Counter(
    "sensorstream_readings_ingested_total",
    "Readings successfully ingested.",
)
ALERTS_TRIGGERED = Counter(
    "sensorstream_alerts_triggered_total",
    "Alerts fired on threshold breach.",
)
INGEST_BATCH_SIZE = Histogram(
    "sensorstream_ingest_batch_size",
    "Distribution of ingest batch sizes (readings per request).",
    buckets=(1, 10, 50, 100, 500, 1_000, 5_000, 10_000),
)

_lock = Lock()

# Monotonic counter: readings ingested since process start.
_readings_ingested = 0
# Monotonic counter: alerts triggered since process start.
_alerts_triggered = 0

# Sliding window of (timestamp, count) for ingestion-rate estimation.
_RATE_WINDOW_SECONDS = 60
_ingest_events: deque[tuple[float, int]] = deque()


def record_ingest(readings: int, alerts: int, *, now: float | None = None) -> None:
    # Prometheus instruments (scrape-based, durable across the scrape window).
    READINGS_INGESTED.inc(readings)
    ALERTS_TRIGGERED.inc(alerts)
    INGEST_BATCH_SIZE.observe(readings)

    # In-process counters behind the /metrics/summary JSON.
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
