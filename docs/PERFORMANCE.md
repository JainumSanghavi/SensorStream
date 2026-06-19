# Performance: the composite index on `readings`

This is the central performance claim of the project: the composite index
`ix_readings_sensor_recorded ON readings (sensor_id, recorded_at DESC)` turns
the hot readings query from a **parallel sequential scan + sort** into a plain
**index scan with no sort**.

## Setup

- PostgreSQL 16 (the docker-compose `db` service).
- ~2,000,000 readings across 12 sensors (`python -m scripts.seed --readings 2000000 --reset`).
- `ANALYZE readings` run before each measurement so the planner has fresh stats.

The measured query is the readings time-range lookup that backs
`GET /sensors/{id}/readings` (newest-first, windowed):

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, sensor_id, value, recorded_at
FROM readings
WHERE sensor_id = 5
  AND recorded_at >= now() - interval '7 days'
  AND recorded_at <= now() - interval '5 days'
ORDER BY recorded_at DESC
LIMIT 50;
```

## BEFORE — index dropped (`DROP INDEX ix_readings_sensor_recorded`)

```
 Limit  (cost=38780.68..38786.51 rows=50 width=32) (actual time=26.008..27.255 rows=50 loops=1)
   Buffers: shared hit=8762 read=6064
   ->  Gather Merge  (cost=38780.68..39848.95 rows=9156 width=32) (actual time=26.005..27.249 rows=50 loops=1)
         Workers Planned: 2
         Workers Launched: 2
         ->  Sort  (cost=37780.65..37792.10 rows=4578 width=32) (actual time=24.876..24.877 rows=34 loops=3)
               Sort Key: recorded_at DESC
               Sort Method: top-N heapsort  Memory: 32kB
               ->  Parallel Seq Scan on readings  (cost=0.00..37628.57 rows=4578 width=32) (actual time=10.882..24.505 rows=3704 loops=3)
                     Filter: ((sensor_id = 5) AND (recorded_at >= ...) AND (recorded_at <= ...))
                     Rows Removed by Filter: 662960
                     Buffers: shared hit=8649 read=6063
 Planning Time: 0.357 ms
 Execution Time: 27.306 ms
```

What's expensive here:
- **Parallel Seq Scan** reads the whole table — each of the 3 workers discards
  **662,960 rows** by filter to find the matches (`Rows Removed by Filter`).
- A separate **top-N heapsort** is needed to satisfy `ORDER BY recorded_at DESC`.
- **~14,826 shared buffers** touched (`hit=8762 read=6064`).
- **27.3 ms** execution — and this grows with table size.

## AFTER — composite index recreated

```
 Limit  (cost=0.44..65.72 rows=50 width=32) (actual time=0.035..0.040 rows=50 loops=1)
   Buffers: shared hit=5 read=3
   ->  Index Scan using ix_readings_sensor_recorded on readings
         (cost=0.44..14806.02 rows=11340 width=32) (actual time=0.034..0.037 rows=50 loops=1)
         Index Cond: ((sensor_id = 5) AND (recorded_at >= ...) AND (recorded_at <= ...))
         Buffers: shared hit=5 read=3
 Planning Time: 0.372 ms
 Execution Time: 0.069 ms
```

What changed:
- **Index Scan** seeks directly to `sensor_id = 5` and walks the `recorded_at`
  range — the time bounds are an `Index Cond`, not a post-filter.
- **No Sort node.** Because the index is ordered `recorded_at DESC`, the rows
  come out already sorted; Postgres reads the index backward-free and the
  `LIMIT 50` stops it after 50 rows.
- **8 shared buffers** touched, down from ~14,826.
- **0.069 ms** execution.

## Result

| Metric                | Before (seq scan) | After (index scan) | Improvement |
| --------------------- | ----------------- | ------------------ | ----------- |
| Execution time        | 27.306 ms         | 0.069 ms           | **~395×**   |
| Shared buffers        | ~14,826           | 8                  | **~1850×**  |
| Rows discarded/worker | 662,960           | 0                  | —           |
| Sort step             | top-N heapsort    | none               | eliminated  |

The win compounds at scale: the seq-scan cost rises linearly with the row count
and degrades further with deeper paging, while the index scan stays flat because
it only ever touches the rows it returns. This is also exactly why
`GET /sensors/{id}/readings` uses **keyset pagination** (see `app/pagination.py`)
rather than `OFFSET` — keyset rides this same index and stays constant-time no
matter how deep the client pages.

## Reproduce

```bash
docker compose up -d db
export DATABASE_URL=postgresql+asyncpg://sensor:sensor@localhost:5432/sensorstream
python -m app.init_db
python -m scripts.seed --readings 2000000 --reset

DB=$(docker compose ps -q db)
# BEFORE
docker exec -i "$DB" psql -U sensor -d sensorstream -c "DROP INDEX ix_readings_sensor_recorded; ANALYZE readings;"
docker exec -i "$DB" psql -U sensor -d sensorstream -c "EXPLAIN (ANALYZE, BUFFERS) SELECT id, sensor_id, value, recorded_at FROM readings WHERE sensor_id = 5 AND recorded_at >= now() - interval '7 days' AND recorded_at <= now() - interval '5 days' ORDER BY recorded_at DESC LIMIT 50;"
# AFTER
docker exec -i "$DB" psql -U sensor -d sensorstream -c "CREATE INDEX ix_readings_sensor_recorded ON readings (sensor_id, recorded_at DESC); ANALYZE readings;"
docker exec -i "$DB" psql -U sensor -d sensorstream -c "EXPLAIN (ANALYZE, BUFFERS) SELECT id, sensor_id, value, recorded_at FROM readings WHERE sensor_id = 5 AND recorded_at >= now() - interval '7 days' AND recorded_at <= now() - interval '5 days' ORDER BY recorded_at DESC LIMIT 50;"
```
