"""Cursor (keyset) pagination correctness on readings."""
from datetime import datetime, timedelta, timezone


async def _seed_readings(client, sensor, n):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    body = {
        "readings": [
            {"value": float(i), "recordedAt": (base + timedelta(seconds=i)).isoformat()}
            for i in range(n)
        ]
    }
    resp = await client.post(f"/sensors/{sensor}/readings", json=body)
    assert resp.status_code == 201


async def test_cursor_pagination_walks_all_rows_once(client, sensor):
    await _seed_readings(client, sensor, 25)

    seen_ids: list[int] = []
    cursor = None
    pages = 0
    while True:
        url = f"/sensors/{sensor}/readings?limit=10"
        if cursor:
            url += f"&cursor={cursor}"
        page = (await client.get(url)).json()
        pages += 1
        ids = [r["id"] for r in page["data"]]
        seen_ids.extend(ids)

        # Within a page, ordering is strictly newest-first.
        recorded = [r["recordedAt"] for r in page["data"]]
        assert recorded == sorted(recorded, reverse=True)

        if not page["pagination"]["hasMore"]:
            assert page["pagination"]["nextCursor"] is None
            break
        cursor = page["pagination"]["nextCursor"]
        assert cursor is not None

    # Every row seen exactly once, no duplicates, no gaps.
    assert len(seen_ids) == 25
    assert len(set(seen_ids)) == 25
    assert pages == 3  # 10 + 10 + 5


async def test_cursor_respects_time_filters(client, sensor):
    await _seed_readings(client, sensor, 20)
    # Values 0..19 map to seconds 0..19 past 2026-01-01.
    frm = datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc).isoformat()
    to = datetime(2026, 1, 1, 0, 0, 14, tzinfo=timezone.utc).isoformat()
    # Pass via params so httpx URL-encodes the "+" in the tz offset.
    page = (
        await client.get(
            f"/sensors/{sensor}/readings",
            params={"from": frm, "to": to, "limit": 100},
        )
    ).json()
    values = sorted(r["value"] for r in page["data"])
    assert values == [float(v) for v in range(5, 15)]


async def test_invalid_cursor_is_422(client, sensor):
    await _seed_readings(client, sensor, 3)
    resp = await client.get(f"/sensors/{sensor}/readings?cursor=not-a-real-cursor")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_cursor"
