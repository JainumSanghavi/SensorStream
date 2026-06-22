"""Observability: the Prometheus /metrics endpoint and the JSON summary."""
from datetime import datetime, timezone


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


async def test_metrics_endpoint_is_prometheus_text(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    # HTTP metrics auto-added by the instrumentator, in exposition format.
    assert "# TYPE" in body
    assert "http_request" in body


async def test_ingest_increments_prometheus_counters(client, sensor):
    body = {"readings": [{"value": 150.0, "recordedAt": _ts()}]}  # breaches threshold
    assert (await client.post(f"/sensors/{sensor}/readings", json=body)).status_code == 201

    metrics = (await client.get("/metrics")).text
    assert "sensorstream_readings_ingested_total" in metrics
    assert "sensorstream_alerts_triggered_total" in metrics
    assert "sensorstream_ingest_batch_size" in metrics


async def test_metrics_summary_is_json(client):
    resp = await client.get("/metrics/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "totalReadings" in data
    assert "activeAlerts" in data
    assert "ingestionRatePerSec" in data
