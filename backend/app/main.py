import asyncio
import json
import re
import secrets

from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from . import alerts_db, analysis, config, influx
from .ws import ConnectionManager

app = FastAPI(title="FactorySense Backend")

influx_client = influx.get_client()
db_pool = ConnectionPool(config.DATABASE_URL, kwargs={"row_factory": dict_row}, min_size=1, max_size=5, open=True)
manager = ConnectionManager()
influx_ready = False

MACHINE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
RANGE_RE = re.compile(r"^\d+[smhdw]$")


class TelemetryIn(BaseModel):
    machine_id: str
    timestamp: str
    vibration: float
    temperature: float
    pressure: float


@app.on_event("startup")
async def wait_for_influx():
    global influx_ready
    for _ in range(30):
        try:
            if influx_client.health().status == "pass":
                influx_ready = True
                return
        except Exception:
            pass
        await asyncio.sleep(2)
    print("[backend] WARNING: InfluxDB not reachable after retries")


async def relay_alert_notifications():
    # Alerts can be created or acknowledged by any replica: each one LISTENs and
    # forwards every notification to the WebSocket clients connected to it.
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(config.DATABASE_URL, autocommit=True) as conn:
                await conn.execute("LISTEN alerts")
                async for notification in conn.notifies():
                    await manager.broadcast(json.loads(notification.payload))
        except psycopg.Error as exc:
            print(f"[backend] alert LISTEN lost, retrying: {exc}")
            await asyncio.sleep(2)


@app.on_event("startup")
async def start_alert_relay():
    app.state.alert_relay = asyncio.create_task(relay_alert_notifications())


@app.get("/health")
def health():
    if not influx_ready:
        raise HTTPException(503, "influxdb not ready")
    return {"status": "ok"}


@app.post("/telemetry", status_code=201)
async def post_telemetry(point: TelemetryIn, x_api_key: str = Header("")):
    # Empty configured key = reject everything (fail closed).
    if not config.SENSOR_API_KEY or not secrets.compare_digest(x_api_key.encode(), config.SENSOR_API_KEY.encode()):
        raise HTTPException(401, "invalid api key")
    if not MACHINE_ID_RE.match(point.machine_id):
        raise HTTPException(400, "invalid machine_id")
    influx.write_point(
        influx_client, point.machine_id, point.vibration, point.temperature, point.pressure, point.timestamp
    )
    new_alert = None
    with db_pool.connection() as conn:
        for sensor in ("vibration", "temperature", "pressure"):
            value = getattr(point, sensor)
            severity = analysis.classify(sensor, value)
            current = alerts_db.get_active_alert(conn, point.machine_id, sensor)
            current_severity = current["severity"] if current else None
            if analysis.should_raise_alert(severity, current_severity):
                threshold = config.THRESHOLDS[sensor][severity]
                new_alert = alerts_db.create_alert(conn, point.machine_id, sensor, severity, value, threshold)
                alerts_db.notify(conn, {"type": "alert_new", "alert": new_alert})
    return {"status": "ok", "alert": new_alert}


@app.get("/machines")
def get_machines():
    result = []
    for machine_id in sorted(influx.query_machine_ids(influx_client)):
        latest = influx.query_latest(influx_client, machine_id)
        if latest is None:
            continue
        statuses = [
            analysis.classify(sensor, latest[sensor])
            for sensor in ("vibration", "temperature", "pressure")
            if sensor in latest
        ]
        result.append({"machine_id": machine_id, "status": analysis.worst_status(statuses), "latest": latest})
    return result


@app.get("/telemetry/history")
def get_history(machine_id: str, sensor: str, time_range: str = Query("1h", alias="range")):
    if not MACHINE_ID_RE.match(machine_id):
        raise HTTPException(400, "invalid machine_id")
    if sensor not in config.THRESHOLDS:
        raise HTTPException(400, "invalid sensor")
    if not RANGE_RE.match(time_range):
        raise HTTPException(400, "invalid range")
    return influx.query_history(influx_client, machine_id, sensor, time_range)


@app.get("/alerts")
def get_alerts(status: str | None = None, machine_id: str | None = None):
    with db_pool.connection() as conn:
        return alerts_db.list_alerts(conn, status=status, machine_id=machine_id)


@app.patch("/alerts/{alert_id}/acknowledge")
def ack_alert(alert_id: int):
    with db_pool.connection() as conn:
        alert = alerts_db.acknowledge_alert(conn, alert_id)
        if alert is None:
            raise HTTPException(404, "alert not found or already acknowledged")
        alerts_db.notify(conn, {"type": "alert_ack", "alert": alert})
    return alert


@app.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
