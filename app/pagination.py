"""Keyset (cursor) pagination helpers for the readings endpoint.

WHY KEYSET, NOT OFFSET
----------------------
`OFFSET n LIMIT k` makes Postgres generate and discard the first `n` rows on
every page. Deep into a multi-million-row table, page 10,000 forces the engine
to walk ~500k rows just to throw them away -- cost grows linearly with depth.

Keyset pagination instead remembers the last row seen and asks for "the next k
rows AFTER this (recorded_at, id)". With the composite index on
(sensor_id, recorded_at DESC) the planner seeks straight to that position and
reads k rows -- cost is independent of how deep you've paged (constant-time).

We encode the cursor as base64("<iso_recorded_at>|<id>"). The `id` tie-breaker
makes ordering total even when two readings share an identical recorded_at, so
no row is ever skipped or duplicated across page boundaries.
"""
import base64
import binascii
from datetime import datetime

from app.errors import AppError


def encode_cursor(recorded_at: datetime, row_id: int) -> str:
    raw = f"{recorded_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        iso, row_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(iso), int(row_id)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise AppError(
            code="invalid_cursor",
            message="The provided cursor is malformed",
            status_code=422,
            details={"cursor": cursor},
        ) from exc
