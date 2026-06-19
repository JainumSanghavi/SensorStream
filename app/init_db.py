"""Apply the SQL schema idempotently. Run on container startup and by tests.

We execute migrations/001_schema.sql directly (rather than metadata.create_all)
so the explicit, documented indexes and CHECK constraints are the ones that
land in the database.
"""
import asyncio
from pathlib import Path

import asyncpg

from app.config import get_settings

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "migrations" / "001_schema.sql"


async def apply_schema() -> None:
    settings = get_settings()
    sql = SCHEMA_FILE.read_text()

    # Retry briefly: in compose the DB healthcheck gates us, but be resilient.
    last_err: Exception | None = None
    for _ in range(30):
        try:
            conn = await asyncpg.connect(settings.asyncpg_dsn)
            break
        except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover - startup race
            last_err = exc
            await asyncio.sleep(1)
    else:  # pragma: no cover
        raise RuntimeError(f"Could not connect to Postgres: {last_err}")

    try:
        await conn.execute(sql)
        print(f"[init_db] applied schema from {SCHEMA_FILE.name}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(apply_schema())
