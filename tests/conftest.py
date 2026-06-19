"""Test fixtures.

Tests run against a REAL Postgres (the same engine features -- date_trunc, COPY,
keyset predicates -- that production uses), in a dedicated `sensorstream_test`
database created on the fly. Point them at a running instance via
TEST_DATABASE_URL (defaults to the docker-compose Postgres on localhost):

    docker compose up -d db
    pytest
"""
import os
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Base DSN (admin) -- the test DB is derived from it.
ADMIN_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://sensor:sensor@localhost:5432/sensorstream",
)
TEST_DB = "sensorstream_test"
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "migrations" / "001_schema.sql"


async def _ensure_test_database() -> None:
    admin_plain = ADMIN_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(admin_plain)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()

    test_plain = TEST_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(test_plain)
    try:
        await conn.execute(SCHEMA_FILE.read_text())
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def engine():
    # Function-scoped so the engine's connections always belong to the same
    # event loop as the test using them (pytest-asyncio creates a loop per test).
    await _ensure_test_database()
    eng = create_async_engine(TEST_URL, pool_pre_ping=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def client(engine, session_factory):
    """An httpx client wired to the app, with the DB dependency overridden and
    all tables truncated for isolation between tests."""
    from app.db import get_session
    from app.main import app

    # Clean slate every test.
    async with engine.begin() as conn:
        from sqlalchemy import text

        await conn.execute(
            text("TRUNCATE alerts, readings, sensors, facilities RESTART IDENTITY CASCADE")
        )

    async def _override():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def sensor(session_factory):
    """Create one facility + sensor (threshold 100.0) and return the sensor id."""
    from app.models import Facility, Sensor

    async with session_factory() as s:
        fac = Facility(name="Test Facility", region="us-east")
        s.add(fac)
        await s.flush()
        sen = Sensor(
            facility_id=fac.id, name="flow-1", type="flow", alert_threshold=100.0
        )
        s.add(sen)
        await s.commit()
        return sen.id
