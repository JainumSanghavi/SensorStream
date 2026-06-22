"""Auth: write endpoints require X-API-Key when API_KEY is configured.

The auth dependency reads settings via Depends(get_settings), so we override
that dependency to simulate a deployment with a key set -- without touching the
process environment or the (unauthenticated) defaults the other tests rely on.
"""
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.main import app


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _with_api_key(value: str) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(api_key=value)


async def test_ingest_rejected_without_key(client, sensor):
    _with_api_key("secret")
    try:
        resp = await client.post(
            f"/sensors/{sensor}/readings",
            json={"readings": [{"value": 1.0, "recordedAt": _ts()}]},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized"
    finally:
        app.dependency_overrides.pop(get_settings, None)


async def test_ingest_accepted_with_key(client, sensor):
    _with_api_key("secret")
    try:
        resp = await client.post(
            f"/sensors/{sensor}/readings",
            json={"readings": [{"value": 1.0, "recordedAt": _ts()}]},
            headers={"X-API-Key": "secret"},
        )
        assert resp.status_code == 201
    finally:
        app.dependency_overrides.pop(get_settings, None)


async def test_delete_rejected_with_wrong_key(client, sensor):
    _with_api_key("secret")
    try:
        resp = await client.delete(
            f"/sensors/{sensor}", headers={"X-API-Key": "wrong"}
        )
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.pop(get_settings, None)


async def test_write_open_when_no_key_configured(client, sensor):
    # Default settings have api_key=None -> auth disabled, no header needed.
    resp = await client.post(
        f"/sensors/{sensor}/readings",
        json={"readings": [{"value": 1.0, "recordedAt": _ts()}]},
    )
    assert resp.status_code == 201
