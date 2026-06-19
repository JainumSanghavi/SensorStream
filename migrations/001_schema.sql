-- ============================================================================
-- SensorStream schema (PostgreSQL 16)
--
-- This file is the source of truth for the database structure. The ORM in
-- app/models.py mirrors it for query construction, but DDL lives HERE so that
-- indexes, constraints, and types are explicit and reviewable -- not an
-- accident of autocreate. The Docker entrypoint (app/init_db.py) executes this
-- file idempotently on startup.
-- ============================================================================

-- enum-like guards kept as CHECK constraints rather than native ENUMs so that
-- adding a new sensor type / severity is a one-line ALTER, not a type rebuild.

CREATE TABLE IF NOT EXISTS facilities (
    id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name    TEXT NOT NULL,
    region  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sensors (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    facility_id     BIGINT NOT NULL REFERENCES facilities (id) ON DELETE CASCADE,
    name            TEXT   NOT NULL,
    type            TEXT   NOT NULL CHECK (type IN ('flow', 'temperature', 'energy', 'pressure')),
    alert_threshold DOUBLE PRECISION NOT NULL
);

-- Foreign-key columns are not auto-indexed by Postgres. We filter and join
-- sensors by facility, so index it explicitly.
CREATE INDEX IF NOT EXISTS ix_sensors_facility_id ON sensors (facility_id);

-- ----------------------------------------------------------------------------
-- readings: the high-volume table (millions of rows). Append-only telemetry.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS readings (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id   BIGINT NOT NULL REFERENCES sensors (id) ON DELETE CASCADE,
    value       DOUBLE PRECISION NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
);

-- COMPOSITE INDEX -- the most important index in the system.
--
-- Every hot query against readings is "give me rows for ONE sensor within a
-- time window, newest first":
--     WHERE sensor_id = $1 AND recorded_at < $cursor
--     ORDER BY recorded_at DESC LIMIT $n
-- and the time-bucketed stats query:
--     WHERE sensor_id = $1 AND recorded_at BETWEEN $from AND $to
--
-- Column order matters: sensor_id FIRST (equality predicate) narrows the scan
-- to a single sensor's slice, then recorded_at (range + sort) lets Postgres
-- walk the index in order and satisfy both the range filter AND the ORDER BY
-- without a separate sort step. DESC matches our newest-first ordering so the
-- planner reads the index backwards with no extra Sort node.
--
-- A single-column index on sensor_id alone would still force a sort + heap
-- fetch of every row for that sensor; the composite makes deep keyset paging
-- effectively constant-time. See docs/PERFORMANCE.md for the before/after plans.
CREATE INDEX IF NOT EXISTS ix_readings_sensor_recorded
    ON readings (sensor_id, recorded_at DESC);

-- ----------------------------------------------------------------------------
-- alerts: created when a reading breaches its sensor's alert_threshold.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id     BIGINT NOT NULL REFERENCES sensors (id) ON DELETE CASCADE,
    severity      TEXT   NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    status        TEXT   NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved')),
    triggered_at  TIMESTAMPTZ NOT NULL,
    reading_value DOUBLE PRECISION NOT NULL
);

-- GET /alerts?status=active is the primary alert query. The cardinality of
-- status is low, but active alerts are the small "hot" subset of a table that
-- grows without bound, so a partial-friendly btree on status keeps that lookup
-- cheap as resolved alerts accumulate.
CREATE INDEX IF NOT EXISTS ix_alerts_status ON alerts (status);

-- Drill-down "show alerts for this sensor" and FK-join support. Like all FK
-- columns, sensor_id is not indexed automatically.
CREATE INDEX IF NOT EXISTS ix_alerts_sensor_id ON alerts (sensor_id);
