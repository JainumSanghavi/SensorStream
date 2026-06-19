"""Ingestion: batch insert, alert firing, validation, missing sensor."""
from datetime import datetime, timedelta, timezone


def _ts(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


async def test_successful_batch_ingest(client, sensor):
    body = {
        "readings": [
            {"value": 10.0, "recordedAt": _ts(0)},
            {"value": 20.0, "recordedAt": _ts(1)},
            {"value": 30.0, "recordedAt": _ts(2)},
        ]
    }
    resp = await client.post(f"/sensors/{sensor}/readings", json=body)
    assert resp.status_code == 201
    data = resp.json()
    assert data["ingested"] == 3
    assert data["alertsTriggered"] == 0
    assert data["sensorId"] == sensor


async def test_alert_fires_on_threshold_breach(client, sensor):
    # threshold is 100.0; two of these breach it.
    body = {
        "readings": [
            {"value": 50.0, "recordedAt": _ts(0)},
            {"value": 150.0, "recordedAt": _ts(1)},   # breach -> high (1.5x)
            {"value": 120.0, "recordedAt": _ts(2)},   # breach -> low  (1.2x)
        ]
    }
    resp = await client.post(f"/sensors/{sensor}/readings", json=body)
    assert resp.status_code == 201
    assert resp.json()["alertsTriggered"] == 2

    alerts = (await client.get("/alerts?status=active")).json()
    assert alerts["pagination"]["total"] == 2
    severities = {a["severity"] for a in alerts["data"]}
    assert severities == {"high", "low"}


async def test_ingest_missing_sensor_404(client):
    resp = await client.post(
        "/sensors/999999/readings",
        json={"readings": [{"value": 1.0, "recordedAt": _ts()}]},
    )
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == "not_found"
    assert err["details"]["id"] == 999999


async def test_invalid_body_422(client, sensor):
    # "value" missing + empty batch are both invalid.
    resp = await client.post(
        f"/sensors/{sensor}/readings",
        json={"readings": [{"recordedAt": _ts()}]},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"

    empty = await client.post(f"/sensors/{sensor}/readings", json={"readings": []})
    assert empty.status_code == 422
