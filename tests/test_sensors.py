"""Sensor CRUD, list envelope, and time-bucketed stats."""
from datetime import datetime, timedelta, timezone


async def test_list_envelope_and_get(client, sensor):
    listing = (await client.get("/sensors")).json()
    assert set(listing.keys()) == {"data", "pagination"}
    assert listing["pagination"]["total"] == 1
    assert listing["data"][0]["alertThreshold"] == 100.0

    one = (await client.get(f"/sensors/{sensor}")).json()
    assert one["id"] == sensor
    assert one["type"] == "flow"


async def test_get_missing_sensor_404(client):
    resp = await client.get("/sensors/424242")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_patch_partial_update(client, sensor):
    resp = await client.patch(f"/sensors/{sensor}", json={"alertThreshold": 75.5})
    assert resp.status_code == 200
    assert resp.json()["alertThreshold"] == 75.5
    # name untouched by the partial update
    assert resp.json()["name"] == "flow-1"


async def test_delete_returns_204(client, sensor):
    resp = await client.delete(f"/sensors/{sensor}")
    assert resp.status_code == 204
    assert (await client.get(f"/sensors/{sensor}")).status_code == 404


async def test_stats_buckets_by_hour(client, sensor):
    base = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
    # 3 readings in hour 10, 2 in hour 11.
    readings = [
        {"value": 10.0, "recordedAt": base.isoformat()},
        {"value": 20.0, "recordedAt": (base + timedelta(minutes=10)).isoformat()},
        {"value": 30.0, "recordedAt": (base + timedelta(minutes=20)).isoformat()},
        {"value": 40.0, "recordedAt": (base + timedelta(hours=1)).isoformat()},
        {"value": 60.0, "recordedAt": (base + timedelta(hours=1, minutes=5)).isoformat()},
    ]
    await client.post(f"/sensors/{sensor}/readings", json={"readings": readings})

    buckets = (await client.get(f"/sensors/{sensor}/stats?interval=hour")).json()
    assert len(buckets) == 2
    first, second = buckets
    assert first["count"] == 3
    assert first["avg"] == 20.0
    assert first["min"] == 10.0
    assert first["max"] == 30.0
    assert second["count"] == 2
    assert second["avg"] == 50.0


async def test_stats_invalid_interval_422(client, sensor):
    resp = await client.get(f"/sensors/{sensor}/stats?interval=week")
    assert resp.status_code == 422
