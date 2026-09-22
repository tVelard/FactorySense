import asyncio
import re

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from . import alerts_db, analysis, config, influx
from .ws import ConnectionManager

app = FastAPI(title="FactorySense Backend")

influx_client = influx.get_client()
db_conn = alerts_db.init_db(config.SQLITE_PATH)
manager = ConnectionManager()
known_machines: set[str] = set()
influx_ready = False

MACHINE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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


@app.get("/health")
def health():
    if not influx_ready:
        raise HTTPException(503, "influxdb not ready")
    return {"status": "ok"}


@app.post("/telemetry", status_code=201)
async def post_telemetry(point: TelemetryIn):
    if not MACHINE_ID_RE.match(point.machine_id):
        raise HTTPException(400, "invalid machine_id")
    known_machines.add(point.machine_id)
    influx.write_point(
        influx_client, point.machine_id, point.vibration, point.temperature, point.pressure, point.timestamp
    )
    new_alert = None
    for sensor in ("vibration", "temperature", "pressure"):
        value = getattr(point, sensor)
        severity = analysis.classify(sensor, value)
        current = alerts_db.get_active_alert(db_conn, point.machine_id, sensor)
        current_severity = current["severity"] if current else None
        if analysis.should_raise_alert(severity, current_severity):
            threshold = config.THRESHOLDS[sensor][severity]
            new_alert = alerts_db.create_alert(db_conn, point.machine_id, sensor, severity, value, threshold)
            await manager.broadcast({"type": "alert_new", "alert": new_alert})
    return {"status": "ok", "alert": new_alert}


@app.get("/machines")
def get_machines():
    result = []
    for machine_id in sorted(known_machines):
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
    return influx.query_history(influx_client, machine_id, sensor, time_range)


@app.get("/alerts")
def get_alerts(status: str | None = None, machine_id: str | None = None):
    return alerts_db.list_alerts(db_conn, status=status, machine_id=machine_id)


@app.patch("/alerts/{alert_id}/acknowledge")
async def ack_alert(alert_id: int):
    alert = alerts_db.acknowledge_alert(db_conn, alert_id)
    if alert is None:
        raise HTTPException(404, "alert not found or already acknowledged")
    await manager.broadcast({"type": "alert_ack", "alert": alert})
    return alert


@app.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
