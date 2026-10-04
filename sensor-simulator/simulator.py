import asyncio
import os
import random
import socket
import time
from datetime import datetime, timezone

import httpx

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000/telemetry")
INTERVAL_SECONDS = float(os.environ.get("INTERVAL_SECONDS", "3"))
API_KEY = os.environ["SENSOR_API_KEY"]
MACHINE_COUNT = int(os.environ.get("MACHINE_COUNT", "3"))

BASELINES = {"vibration": 2.0, "temperature": 45.0, "pressure": 5.0}
VIBRATION_DRIFT_PER_SECOND = 0.02
TEMPERATURE_DRIFT_PER_SECOND = 0.08


def make_machine_id(local_index: int) -> str:
    return f"{socket.gethostname()}-{local_index}"


def build_point(machine_id: str, elapsed_seconds: float, drifting: bool) -> dict:
    drift = min(elapsed_seconds, 400.0) if drifting else 0.0
    return {
        "machine_id": machine_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "vibration": round(BASELINES["vibration"] + drift * VIBRATION_DRIFT_PER_SECOND + random.gauss(0, 0.2), 2),
        "temperature": round(
            BASELINES["temperature"] + drift * TEMPERATURE_DRIFT_PER_SECOND + random.gauss(0, 1.0), 2
        ),
        "pressure": round(BASELINES["pressure"] + random.gauss(0, 0.15), 2),
    }


async def run_machine(client: httpx.AsyncClient, local_index: int, drifting: bool):
    machine_id = make_machine_id(local_index)
    start = time.monotonic()
    while True:
        point = build_point(machine_id, time.monotonic() - start, drifting)
        try:
            await client.post(BACKEND_URL, json=point, timeout=5.0)
        except httpx.HTTPError as exc:
            print(f"[simulator] POST failed for {machine_id}: {exc}")
        await asyncio.sleep(INTERVAL_SECONDS)


async def main():
    async with httpx.AsyncClient(headers={"X-API-Key": API_KEY}) as client:
        tasks = [run_machine(client, i, drifting=(i == 0)) for i in range(MACHINE_COUNT)]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
