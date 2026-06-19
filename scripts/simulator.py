"""Live ingestion simulator: POST a fresh reading every few seconds.

Demonstrates real-time ingestion + live alerting against a running API. It
occasionally emits a spike so you can watch an alert fire in /alerts and the
counters move in /metrics.

Usage:
    python -m scripts.simulator --sensor 1 --interval 2 --base-url http://localhost:8000
"""
import argparse
import asyncio
import math
import random
from datetime import datetime, timezone

import httpx

from scripts.seed import PROFILES


async def run(base_url: str, sensor_id: int, interval: float) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        # Look up the sensor so we mimic its type's profile + threshold.
        resp = await client.get(f"/sensors/{sensor_id}")
        resp.raise_for_status()
        sensor = resp.json()
        profile = PROFILES.get(sensor["type"], PROFILES["flow"])
        threshold = sensor["alertThreshold"]
        print(f"[sim] streaming to sensor {sensor_id} ({sensor['type']}), "
              f"threshold={threshold}, every {interval}s. Ctrl-C to stop.")

        while True:
            now = datetime.now(timezone.utc)
            phase = 2 * math.pi * (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0
            spike = random.random() < 0.1  # 10% spike rate so alerts are visible live
            if spike:
                value = round(threshold * random.uniform(1.05, 1.5), 4)
            else:
                value = round(
                    profile["baseline"]
                    + profile["amplitude"] * math.sin(phase)
                    + random.gauss(0, profile["noise"]),
                    4,
                )

            r = await client.post(
                f"/sensors/{sensor_id}/readings",
                json={"readings": [{"value": value, "recordedAt": now.isoformat()}]},
            )
            summary = r.json()
            flag = "  <-- ALERT" if summary.get("alertsTriggered") else ""
            print(f"[sim] value={value:<10} ingested={summary.get('ingested')}{flag}")
            await asyncio.sleep(interval)


def main() -> None:
    p = argparse.ArgumentParser(description="Live sensor reading simulator.")
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--sensor", type=int, default=1, dest="sensor_id")
    p.add_argument("--interval", type=float, default=2.0, help="seconds between readings")
    args = p.parse_args()
    try:
        asyncio.run(run(args.base_url, args.sensor_id, args.interval))
    except KeyboardInterrupt:
        print("\n[sim] stopped")


if __name__ == "__main__":
    main()
