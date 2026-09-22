# FactorySense Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working Docker Compose prototype of FactorySense — telemetry ingestion, threshold-based predictive alerts, and a live dashboard — matching the approved design spec.

**Architecture:** A Python sensor simulator posts fake telemetry to a FastAPI backend, which writes time series to InfluxDB, evaluates thresholds (edge-triggered, two severities), and stores mutable alert state in an embedded SQLite file. A Node/Express frontend acts as a Backend-For-Frontend: the browser only ever talks to Node, which proxies REST calls and relays a single upstream WebSocket connection to all connected browsers.

**Tech Stack:** Python 3.12 (FastAPI, uvicorn, influxdb-client, httpx), InfluxDB 2.7, SQLite (stdlib `sqlite3`), Node 20 (Express, ejs, ws), Chart.js (CDN), Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-22-factorysense-design.md`

## Global Constraints

- InfluxDB requires token authentication; no anonymous access.
- SQLite lives as a file inside the backend container — it is not a separate Docker service.
- Alerts are edge-triggered: a new alert row is only created when severity increases past the current active alert for that (machine_id, sensor) pair; readings dropping back to "ok" do NOT auto-resolve an alert — only manual acknowledgement does.
- `machine_id` format is `<container-hostname>-<local-index>` so scaling `sensor-simulator` never collides.
- The browser only ever talks to the Node frontend (BFF pattern) — never directly to the backend or InfluxDB from client-side JS.
- Secrets live in a local `.env` (gitignored); `.env.example` is committed with placeholder values.
- No user authentication on the dashboard (explicitly out of scope per spec section 8).
- No test framework dependencies beyond `pytest` (backend) and Node's built-in `assert` + the already-required `ws` package (frontend) — no Jest/Mocha.

---

## File Structure

```
FactorySense/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py        # thresholds + env var loading
│   │   ├── analysis.py      # classify(), should_raise_alert(), worst_status()
│   │   ├── alerts_db.py     # SQLite: init_db, get_active_alert, create_alert, list_alerts, acknowledge_alert
│   │   ├── influx.py        # InfluxDB client: get_client, write_point, query_latest, query_history
│   │   ├── ws.py            # ConnectionManager (WebSocket broadcast)
│   │   └── main.py          # FastAPI app: all routes
│   └── tests/
│       ├── conftest.py
│       ├── test_analysis.py
│       ├── test_alerts_db.py
│       ├── test_ws.py
│       └── test_alerts_api.py   # integration, runs against the live compose stack
├── sensor-simulator/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── simulator.py
└── frontend/
    ├── Dockerfile
    ├── .dockerignore
    ├── package.json
    ├── server.js
    ├── views/
    │   └── dashboard.ejs
    ├── public/
    │   ├── dashboard.js
    │   └── style.css
    └── test/
        └── ws-relay.test.js   # integration, runs against the live compose stack
```

---

### Task 1: Repo scaffolding + InfluxDB service

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `docker-compose.yml`
- Create: `README.md` (stub — filled in Task 8)

**Interfaces:**
- Produces: a running `influxdb` container reachable at `http://localhost:8086`, with org/bucket/token taken from `.env`. Later tasks read `INFLUX_URL`, `INFLUX_TOKEN`, `INFLUX_ORG`, `INFLUX_BUCKET` from the environment.

- [ ] **Step 1: Create `.gitignore`**

```
__pycache__/
*.pyc
.env
node_modules/
*.db
.pytest_cache/
```

- [ ] **Step 2: Create `.env.example`**

```
INFLUX_PASSWORD=changeme123
INFLUX_ORG=factorysense
INFLUX_BUCKET=telemetry
INFLUX_TOKEN=devtoken_change_me_please
```

- [ ] **Step 3: Create `docker-compose.yml` with the InfluxDB service**

```yaml
services:
  influxdb:
    image: influxdb:2.7
    environment:
      DOCKER_INFLUXDB_INIT_MODE: setup
      DOCKER_INFLUXDB_INIT_USERNAME: admin
      DOCKER_INFLUXDB_INIT_PASSWORD: ${INFLUX_PASSWORD}
      DOCKER_INFLUXDB_INIT_ORG: ${INFLUX_ORG}
      DOCKER_INFLUXDB_INIT_BUCKET: ${INFLUX_BUCKET}
      DOCKER_INFLUXDB_INIT_ADMIN_TOKEN: ${INFLUX_TOKEN}
    ports:
      - "8086:8086"
    volumes:
      - influxdb-data:/var/lib/influxdb2
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8086/health"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  influxdb-data:
```

- [ ] **Step 4: Create README.md stub**

```markdown
# FactorySense

Prototype en cours de construction. Voir `docs/superpowers/specs/2026-09-22-factorysense-design.md` pour la conception complète. Ce README sera complété une fois le prototype fonctionnel.
```

- [ ] **Step 5: Bring up InfluxDB and verify health**

```bash
cp .env.example .env
docker compose up -d influxdb
docker compose ps
curl -s http://localhost:8086/health
```

Expected: `docker compose ps` shows `influxdb` as `healthy`; the curl response contains `"status":"pass"`.

- [ ] **Step 6: Commit**

```bash
git add .gitignore .env.example docker-compose.yml README.md
git commit -m "chore: scaffold repo and bring up InfluxDB service"
```

---

### Task 2: Backend — config + threshold analysis logic

**Files:**
- Create: `backend/app/__init__.py` (empty)
- Create: `backend/app/config.py`
- Create: `backend/app/analysis.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_analysis.py`
- Create: `backend/requirements-dev.txt`

**Interfaces:**
- Produces: `config.THRESHOLDS: dict[str, dict[str, float]]` keyed by sensor name (`"vibration"`, `"temperature"`, `"pressure"`), each with `"warning"` and `"critical"` float keys. `analysis.classify(sensor: str, value: float) -> str` returns `"ok"`/`"warning"`/`"critical"`. `analysis.should_raise_alert(new_severity: str, current_active_severity: str | None) -> bool`. `analysis.worst_status(statuses: list[str]) -> str`.
- Consumed by: Task 5's `main.py`.

- [ ] **Step 1: Create `backend/tests/conftest.py` so tests can import `app` without packaging**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

- [ ] **Step 2: Write the failing test — `backend/tests/test_analysis.py`**

```python
from app.analysis import classify, should_raise_alert, worst_status


def test_classify_ok_below_warning_threshold():
    assert classify("vibration", 2.0) == "ok"


def test_classify_warning_at_threshold():
    assert classify("vibration", 4.0) == "warning"


def test_classify_critical_at_threshold():
    assert classify("vibration", 6.0) == "critical"


def test_classify_temperature_uses_its_own_thresholds():
    assert classify("temperature", 70.0) == "warning"
    assert classify("temperature", 85.0) == "critical"
    assert classify("temperature", 50.0) == "ok"


def test_should_raise_alert_on_first_warning():
    assert should_raise_alert("warning", None) is True


def test_should_raise_alert_escalation_from_warning_to_critical():
    assert should_raise_alert("critical", "warning") is True


def test_should_not_raise_alert_for_same_or_lower_severity():
    assert should_raise_alert("warning", "warning") is False
    assert should_raise_alert("warning", "critical") is False


def test_should_not_raise_alert_when_ok():
    assert should_raise_alert("ok", None) is False
    assert should_raise_alert("ok", "warning") is False


def test_worst_status_picks_highest_severity():
    assert worst_status(["ok", "warning", "ok"]) == "warning"
    assert worst_status(["ok", "critical", "warning"]) == "critical"
    assert worst_status([]) == "ok"
```

- [ ] **Step 3: Create `backend/requirements-dev.txt` and run the test to verify it fails**

```
pytest==8.3.3
```

Run:
```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests/test_analysis.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis'` (or `app` package missing).

- [ ] **Step 4: Create `backend/app/__init__.py`** (empty file)

- [ ] **Step 5: Implement `backend/app/config.py`**

```python
import os

THRESHOLDS = {
    "vibration": {"warning": 4.0, "critical": 6.0, "unit": "mm/s"},
    "temperature": {"warning": 70.0, "critical": 85.0, "unit": "°C"},
    "pressure": {"warning": 8.0, "critical": 10.0, "unit": "bar"},
}

INFLUX_URL = os.environ.get("INFLUX_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.environ.get("INFLUX_TOKEN", "")
INFLUX_ORG = os.environ.get("INFLUX_ORG", "factorysense")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "telemetry")
SQLITE_PATH = os.environ.get("SQLITE_PATH", "/data/alerts.db")
```

- [ ] **Step 6: Implement `backend/app/analysis.py`**

```python
from . import config

SEVERITY_ORDER = {"ok": 0, "warning": 1, "critical": 2}


def classify(sensor: str, value: float) -> str:
    thresholds = config.THRESHOLDS[sensor]
    if value >= thresholds["critical"]:
        return "critical"
    if value >= thresholds["warning"]:
        return "warning"
    return "ok"


def should_raise_alert(new_severity: str, current_active_severity: str | None) -> bool:
    if new_severity == "ok":
        return False
    if current_active_severity is None:
        return True
    return SEVERITY_ORDER[new_severity] > SEVERITY_ORDER[current_active_severity]


def worst_status(statuses: list[str]) -> str:
    if not statuses:
        return "ok"
    return max(statuses, key=lambda s: SEVERITY_ORDER[s])
```

- [ ] **Step 7: Run the test to verify it passes**

```bash
cd backend
python -m pytest tests/test_analysis.py -v
```
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/__init__.py backend/app/config.py backend/app/analysis.py backend/tests/conftest.py backend/tests/test_analysis.py backend/requirements-dev.txt
git commit -m "feat(backend): add threshold config and edge-triggered alert analysis"
```

---

### Task 3: Backend — SQLite alert store

**Files:**
- Create: `backend/app/alerts_db.py`
- Test: `backend/tests/test_alerts_db.py`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces: `alerts_db.init_db(path: str) -> sqlite3.Connection`. `alerts_db.get_active_alert(conn, machine_id: str, sensor: str) -> dict | None`. `alerts_db.create_alert(conn, machine_id: str, sensor: str, severity: str, value: float, threshold: float) -> dict`. `alerts_db.list_alerts(conn, status: str | None = None, machine_id: str | None = None) -> list[dict]`. `alerts_db.acknowledge_alert(conn, alert_id: int) -> dict | None`. Every alert dict has keys: `id, machine_id, sensor, severity, value, threshold, raised_at, status, acknowledged_at`.
- Consumed by: Task 5's `main.py`.

- [ ] **Step 1: Write the failing test — `backend/tests/test_alerts_db.py`**

```python
from pathlib import Path

from app import alerts_db


def _new_db(tmp_path: Path):
    return alerts_db.init_db(str(tmp_path / "alerts.db"))


def test_get_active_alert_returns_none_when_no_alerts(tmp_path):
    conn = _new_db(tmp_path)
    assert alerts_db.get_active_alert(conn, "machine-1", "vibration") is None


def test_create_alert_returns_active_alert_with_expected_fields(tmp_path):
    conn = _new_db(tmp_path)
    alert = alerts_db.create_alert(conn, "machine-1", "vibration", "warning", 4.5, 4.0)
    assert alert["machine_id"] == "machine-1"
    assert alert["sensor"] == "vibration"
    assert alert["severity"] == "warning"
    assert alert["status"] == "active"
    assert alert["acknowledged_at"] is None
    assert alert["id"] is not None


def test_get_active_alert_finds_most_recent_active_alert(tmp_path):
    conn = _new_db(tmp_path)
    alerts_db.create_alert(conn, "machine-1", "vibration", "warning", 4.5, 4.0)
    second = alerts_db.create_alert(conn, "machine-1", "vibration", "critical", 6.5, 6.0)
    active = alerts_db.get_active_alert(conn, "machine-1", "vibration")
    assert active["id"] == second["id"]
    assert active["severity"] == "critical"


def test_list_alerts_filters_by_status_and_machine(tmp_path):
    conn = _new_db(tmp_path)
    a1 = alerts_db.create_alert(conn, "machine-1", "vibration", "warning", 4.5, 4.0)
    alerts_db.create_alert(conn, "machine-2", "temperature", "critical", 90.0, 85.0)
    alerts_db.acknowledge_alert(conn, a1["id"])

    active = alerts_db.list_alerts(conn, status="active")
    assert len(active) == 1
    assert active[0]["machine_id"] == "machine-2"

    machine1_alerts = alerts_db.list_alerts(conn, machine_id="machine-1")
    assert len(machine1_alerts) == 1
    assert machine1_alerts[0]["status"] == "acknowledged"


def test_acknowledge_alert_sets_status_and_timestamp(tmp_path):
    conn = _new_db(tmp_path)
    alert = alerts_db.create_alert(conn, "machine-1", "vibration", "warning", 4.5, 4.0)
    acknowledged = alerts_db.acknowledge_alert(conn, alert["id"])
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["acknowledged_at"] is not None


def test_acknowledge_alert_returns_none_for_unknown_id(tmp_path):
    conn = _new_db(tmp_path)
    assert alerts_db.acknowledge_alert(conn, 9999) is None


def test_acknowledge_alert_returns_none_if_already_acknowledged(tmp_path):
    conn = _new_db(tmp_path)
    alert = alerts_db.create_alert(conn, "machine-1", "vibration", "warning", 4.5, 4.0)
    alerts_db.acknowledge_alert(conn, alert["id"])
    assert alerts_db.acknowledge_alert(conn, alert["id"]) is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend
python -m pytest tests/test_alerts_db.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.alerts_db'`.

- [ ] **Step 3: Implement `backend/app/alerts_db.py`**

```python
import sqlite3
from datetime import datetime, timezone


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT NOT NULL,
            sensor TEXT NOT NULL,
            severity TEXT NOT NULL,
            value REAL NOT NULL,
            threshold REAL NOT NULL,
            raised_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            acknowledged_at TEXT
        )
        """
    )
    conn.commit()
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def get_active_alert(conn: sqlite3.Connection, machine_id: str, sensor: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM alerts WHERE machine_id = ? AND sensor = ? AND status = 'active' "
        "ORDER BY raised_at DESC LIMIT 1",
        (machine_id, sensor),
    ).fetchone()
    return _row_to_dict(row)


def get_alert_by_id(conn: sqlite3.Connection, alert_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    return _row_to_dict(row)


def create_alert(
    conn: sqlite3.Connection,
    machine_id: str,
    sensor: str,
    severity: str,
    value: float,
    threshold: float,
) -> dict:
    raised_at = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO alerts (machine_id, sensor, severity, value, threshold, raised_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'active')",
        (machine_id, sensor, severity, value, threshold, raised_at),
    )
    conn.commit()
    return get_alert_by_id(conn, cur.lastrowid)


def list_alerts(
    conn: sqlite3.Connection, status: str | None = None, machine_id: str | None = None
) -> list[dict]:
    query = "SELECT * FROM alerts WHERE 1=1"
    params: list[str] = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if machine_id:
        query += " AND machine_id = ?"
        params.append(machine_id)
    query += " ORDER BY raised_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def acknowledge_alert(conn: sqlite3.Connection, alert_id: int) -> dict | None:
    alert = get_alert_by_id(conn, alert_id)
    if alert is None or alert["status"] == "acknowledged":
        return None
    acknowledged_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE alerts SET status = 'acknowledged', acknowledged_at = ? WHERE id = ?",
        (acknowledged_at, alert_id),
    )
    conn.commit()
    return get_alert_by_id(conn, alert_id)
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd backend
python -m pytest tests/test_alerts_db.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/alerts_db.py backend/tests/test_alerts_db.py
git commit -m "feat(backend): add SQLite-backed mutable alert store"
```

---

### Task 4: Backend — InfluxDB client wrapper + WebSocket connection manager

**Files:**
- Create: `backend/app/influx.py`
- Create: `backend/app/ws.py`
- Test: `backend/tests/test_ws.py`
- Create: `backend/requirements.txt`

**Interfaces:**
- Produces: `influx.get_client() -> InfluxDBClient`. `influx.write_point(client, machine_id: str, vibration: float, temperature: float, pressure: float, timestamp: str) -> None`. `influx.query_latest(client, machine_id: str) -> dict | None` (keys: `vibration, temperature, pressure, timestamp`). `influx.query_history(client, machine_id: str, sensor: str, range_str: str) -> list[dict]` (each item: `{"timestamp": str, "value": float}`). `ws.ConnectionManager` with `async connect(websocket)`, `disconnect(websocket)`, `async broadcast(message: dict)`.
- Consumed by: Task 5's `main.py`.
- Note: `influx.py` has no automated unit test here — it needs a live InfluxDB, and is exercised end-to-end by the integration tests in Task 5. `ws.py` is pure and gets full unit tests using fake WebSocket objects.

- [ ] **Step 1: Write the failing test — `backend/tests/test_ws.py`**

```python
import asyncio

from app.ws import ConnectionManager


class FakeWebSocket:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_text(self, data):
        if self.fail:
            raise RuntimeError("connection closed")
        self.sent.append(data)


def test_connect_accepts_and_tracks_websocket():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    asyncio.run(manager.connect(ws))
    assert ws.accepted is True
    assert ws in manager.active


def test_broadcast_sends_json_to_all_connected_clients():
    manager = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    asyncio.run(manager.connect(ws1))
    asyncio.run(manager.connect(ws2))
    asyncio.run(manager.broadcast({"type": "alert_new", "alert": {"id": 1}}))
    assert "alert_new" in ws1.sent[0]
    assert "alert_new" in ws2.sent[0]


def test_broadcast_drops_clients_that_fail_to_send():
    manager = ConnectionManager()
    good, bad = FakeWebSocket(), FakeWebSocket(fail=True)
    asyncio.run(manager.connect(good))
    asyncio.run(manager.connect(bad))
    asyncio.run(manager.broadcast({"type": "ping"}))
    assert bad not in manager.active
    assert good in manager.active


def test_disconnect_removes_websocket():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    asyncio.run(manager.connect(ws))
    manager.disconnect(ws)
    assert ws not in manager.active
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend
python -m pytest tests/test_ws.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ws'`.

- [ ] **Step 3: Implement `backend/app/ws.py`**

```python
import json

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active:
            self.active.remove(websocket)

    async def broadcast(self, message: dict):
        payload = json.dumps(message)
        stale = []
        for ws in self.active:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)
```

- [ ] **Step 4: Create `backend/requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
influxdb-client==1.45.0
```

- [ ] **Step 5: Install deps and run the test to verify it passes**

```bash
cd backend
pip install -r requirements.txt
python -m pytest tests/test_ws.py -v
```
Expected: all tests PASS.

- [ ] **Step 6: Implement `backend/app/influx.py`**

```python
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from . import config


def get_client() -> InfluxDBClient:
    return InfluxDBClient(url=config.INFLUX_URL, token=config.INFLUX_TOKEN, org=config.INFLUX_ORG)


def write_point(client, machine_id, vibration, temperature, pressure, timestamp):
    write_api = client.write_api(write_options=SYNCHRONOUS)
    point = (
        Point("telemetry")
        .tag("machine_id", machine_id)
        .field("vibration", vibration)
        .field("temperature", temperature)
        .field("pressure", pressure)
        .time(timestamp)
    )
    write_api.write(bucket=config.INFLUX_BUCKET, record=point)


def query_latest(client, machine_id):
    query_api = client.query_api()
    flux = f"""
    from(bucket: "{config.INFLUX_BUCKET}")
      |> range(start: -1h)
      |> filter(fn: (r) => r._measurement == "telemetry" and r.machine_id == "{machine_id}")
      |> last()
    """
    tables = query_api.query(flux, org=config.INFLUX_ORG)
    result: dict = {}
    latest_time = None
    for table in tables:
        for record in table.records:
            result[record.get_field()] = record.get_value()
            latest_time = record.get_time()
    if not result:
        return None
    result["timestamp"] = latest_time.isoformat() if latest_time else None
    return result


def query_history(client, machine_id, sensor, range_str):
    query_api = client.query_api()
    flux = f"""
    from(bucket: "{config.INFLUX_BUCKET}")
      |> range(start: -{range_str})
      |> filter(fn: (r) => r._measurement == "telemetry" and r.machine_id == "{machine_id}" and r._field == "{sensor}")
      |> sort(columns: ["_time"])
    """
    tables = query_api.query(flux, org=config.INFLUX_ORG)
    points = []
    for table in tables:
        for record in table.records:
            points.append({"timestamp": record.get_time().isoformat(), "value": record.get_value()})
    return points
```

- [ ] **Step 7: Sanity-check `influx.py` imports cleanly**

```bash
cd backend
python -c "import app.influx"
```
Expected: no output, exit code 0 (a real live-query check happens in Task 5 against the running stack).

- [ ] **Step 8: Commit**

```bash
git add backend/app/influx.py backend/app/ws.py backend/tests/test_ws.py backend/requirements.txt
git commit -m "feat(backend): add InfluxDB client wrapper and WebSocket connection manager"
```

---

### Task 5: Backend — FastAPI app, Docker image, integration tests

**Files:**
- Create: `backend/app/main.py`
- Create: `backend/Dockerfile`
- Modify: `docker-compose.yml` (add `backend` service)
- Modify: `backend/requirements-dev.txt` (add `requests`)
- Test: `backend/tests/test_alerts_api.py` (integration, runs against the live stack)

**Interfaces:**
- Consumes: `config.THRESHOLDS`, `config.SQLITE_PATH`; `analysis.classify`, `analysis.should_raise_alert`, `analysis.worst_status`; `alerts_db.init_db`, `alerts_db.get_active_alert`, `alerts_db.create_alert`, `alerts_db.list_alerts`, `alerts_db.acknowledge_alert`; `influx.get_client`, `influx.write_point`, `influx.query_latest`, `influx.query_history`; `ws.ConnectionManager`.
- Produces the HTTP/WS contract every later task relies on:
  - `POST /telemetry` — body `{machine_id, timestamp, vibration, temperature, pressure}` → `201 {"status": "ok", "alert": <alert dict>|null}`.
  - `GET /machines` → `[{"machine_id": str, "status": "ok"|"warning"|"critical", "latest": {...}}]`.
  - `GET /telemetry/history?machine_id=&sensor=&range=` → `[{"timestamp": str, "value": float}]`.
  - `GET /alerts?status=&machine_id=` → `[<alert dict>]`.
  - `PATCH /alerts/{id}/acknowledge` → `200 <alert dict>` or `404`.
  - `WS /ws/alerts` — pushes `{"type": "alert_new"|"alert_ack", "alert": <alert dict>}`.
  - `GET /health` → `200 {"status": "ok"}` once InfluxDB is reachable, else `503`.

- [ ] **Step 1: Implement `backend/app/main.py`**

```python
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
```

- [ ] **Step 2: Create `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Modify `docker-compose.yml` — add the `backend` service**

Add under `services:` (after `influxdb`):

```yaml
  backend:
    build: ./backend
    environment:
      INFLUX_URL: http://influxdb:8086
      INFLUX_TOKEN: ${INFLUX_TOKEN}
      INFLUX_ORG: ${INFLUX_ORG}
      INFLUX_BUCKET: ${INFLUX_BUCKET}
      SQLITE_PATH: /data/alerts.db
    volumes:
      - backend-data:/data
    depends_on:
      influxdb:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 5s
      timeout: 3s
      retries: 10
    ports:
      - "8000:8000"
```

And add `backend-data:` under the top-level `volumes:` key alongside `influxdb-data:`.

- [ ] **Step 4: Build and start influxdb + backend**

```bash
docker compose up -d --build influxdb backend
docker compose ps
```
Expected: both services show `healthy` (backend may take a few seconds while it waits for InfluxDB).

- [ ] **Step 5: Add `requests` to `backend/requirements-dev.txt`**

```
pytest==8.3.3
requests==2.32.3
```

- [ ] **Step 6: Write the integration test — `backend/tests/test_alerts_api.py`**

```python
import time

import requests

BASE_URL = "http://localhost:8000"


def _unique_machine_id():
    return f"test-machine-{int(time.time() * 1000)}"


def test_normal_point_does_not_raise_alert():
    machine_id = _unique_machine_id()
    payload = {
        "machine_id": machine_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "vibration": 2.0,
        "temperature": 45.0,
        "pressure": 5.0,
    }
    resp = requests.post(f"{BASE_URL}/telemetry", json=payload, timeout=5)
    assert resp.status_code == 201
    assert resp.json()["alert"] is None

    alerts = requests.get(f"{BASE_URL}/alerts", params={"machine_id": machine_id}, timeout=5).json()
    assert alerts == []


def test_critical_point_raises_alert_and_can_be_acknowledged():
    machine_id = _unique_machine_id()
    payload = {
        "machine_id": machine_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "vibration": 7.0,
        "temperature": 45.0,
        "pressure": 5.0,
    }
    resp = requests.post(f"{BASE_URL}/telemetry", json=payload, timeout=5)
    assert resp.status_code == 201
    alert = resp.json()["alert"]
    assert alert is not None
    assert alert["severity"] == "critical"
    assert alert["sensor"] == "vibration"

    active = requests.get(
        f"{BASE_URL}/alerts", params={"machine_id": machine_id, "status": "active"}, timeout=5
    ).json()
    assert len(active) == 1
    assert active[0]["id"] == alert["id"]

    ack_resp = requests.patch(f"{BASE_URL}/alerts/{alert['id']}/acknowledge", timeout=5)
    assert ack_resp.status_code == 200
    assert ack_resp.json()["status"] == "acknowledged"

    still_active = requests.get(
        f"{BASE_URL}/alerts", params={"machine_id": machine_id, "status": "active"}, timeout=5
    ).json()
    assert still_active == []
```

- [ ] **Step 7: Run the integration tests against the live stack**

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests/test_alerts_api.py -v
```
Expected: both tests PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/main.py backend/Dockerfile docker-compose.yml backend/requirements-dev.txt backend/tests/test_alerts_api.py
git commit -m "feat(backend): wire FastAPI app with ingestion, alerting, and WebSocket endpoints"
```

---

### Task 6: Sensor simulator

**Files:**
- Create: `sensor-simulator/simulator.py`
- Create: `sensor-simulator/requirements.txt`
- Create: `sensor-simulator/Dockerfile`
- Modify: `docker-compose.yml` (add `sensor-simulator` service)

**Interfaces:**
- Consumes: `POST http://backend:8000/telemetry` with body `{machine_id, timestamp, vibration, temperature, pressure}` (as defined in Task 5).
- Produces: continuous telemetry for `MACHINE_COUNT` machines per container instance; `machine_id` is `f"{socket.gethostname()}-{local_index}"`.

- [ ] **Step 1: Implement `sensor-simulator/simulator.py`**

```python
import asyncio
import os
import random
import socket
import time
from datetime import datetime, timezone

import httpx

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000/telemetry")
INTERVAL_SECONDS = float(os.environ.get("INTERVAL_SECONDS", "3"))
MACHINE_COUNT = int(os.environ.get("MACHINE_COUNT", "3"))

BASELINES = {"vibration": 2.0, "temperature": 45.0, "pressure": 5.0}
# Drift rates (per second of container uptime) applied only to the first
# simulated machine in each container, so the demo shows one machine
# degrading toward failure while its siblings stay in the "ok" band.
VIBRATION_DRIFT_PER_SECOND = 0.02
TEMPERATURE_DRIFT_PER_SECOND = 0.08


def make_machine_id(local_index: int) -> str:
    return f"{socket.gethostname()}-{local_index}"


def build_point(machine_id: str, elapsed_seconds: float, drifting: bool) -> dict:
    drift = elapsed_seconds if drifting else 0.0
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
    async with httpx.AsyncClient() as client:
        tasks = [run_machine(client, i, drifting=(i == 0)) for i in range(MACHINE_COUNT)]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Create `sensor-simulator/requirements.txt`**

```
httpx==0.27.2
```

- [ ] **Step 3: Create `sensor-simulator/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY simulator.py .
CMD ["python", "simulator.py"]
```

- [ ] **Step 4: Modify `docker-compose.yml` — add the `sensor-simulator` service**

Add under `services:` (after `backend`):

```yaml
  sensor-simulator:
    build: ./sensor-simulator
    environment:
      BACKEND_URL: http://backend:8000/telemetry
      INTERVAL_SECONDS: "3"
      MACHINE_COUNT: "3"
    depends_on:
      backend:
        condition: service_healthy
```

- [ ] **Step 5: Build, start, and verify telemetry is flowing**

```bash
docker compose up -d --build sensor-simulator
sleep 10
python3 -c "
import requests
data = requests.get('http://localhost:8000/machines').json()
assert len(data) == 3, f'expected 3 machines, got {len(data)}'
print('OK:', [m['machine_id'] for m in data])
"
```
Expected: prints `OK:` followed by 3 machine IDs shaped like `<hostname>-0`, `<hostname>-1`, `<hostname>-2`.

- [ ] **Step 6: Commit**

```bash
git add sensor-simulator/simulator.py sensor-simulator/requirements.txt sensor-simulator/Dockerfile docker-compose.yml
git commit -m "feat(simulator): generate telemetry for 3 machines with one progressive drift"
```

---

### Task 7: Frontend dashboard (Node/Express BFF)

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/server.js`
- Create: `frontend/views/dashboard.ejs`
- Create: `frontend/public/dashboard.js`
- Create: `frontend/public/style.css`
- Create: `frontend/Dockerfile`
- Create: `frontend/.dockerignore`
- Test: `frontend/test/ws-relay.test.js` (integration, runs against the live stack)
- Modify: `docker-compose.yml` (add `frontend` service)

**Interfaces:**
- Consumes: backend REST endpoints and `WS /ws/alerts` as defined in Task 5.
- Produces: `GET /` (dashboard page), `GET /api/history`, `POST /api/alerts/:id/ack`, and a browser-facing `WS /ws` that relays backend broadcast messages verbatim (`{"type": "alert_new"|"alert_ack", "alert": {...}}`).

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "factorysense-frontend",
  "version": "1.0.0",
  "private": true,
  "main": "server.js",
  "scripts": {
    "start": "node server.js"
  },
  "dependencies": {
    "express": "^4.19.2",
    "ejs": "^3.1.10",
    "ws": "^8.18.0"
  }
}
```

- [ ] **Step 2: Implement `frontend/server.js`**

```javascript
const express = require('express');
const path = require('path');
const http = require('http');
const WebSocket = require('ws');

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000';
const BACKEND_WS_URL = process.env.BACKEND_WS_URL || 'ws://backend:8000/ws/alerts';
const PORT = process.env.PORT || 3000;

const app = express();
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use(express.static(path.join(__dirname, 'public')));
app.use(express.json());

app.get('/', async (req, res) => {
  try {
    const [machinesRes, alertsRes] = await Promise.all([
      fetch(`${BACKEND_URL}/machines`),
      fetch(`${BACKEND_URL}/alerts?status=active`),
    ]);
    const machines = await machinesRes.json();
    const activeAlerts = await alertsRes.json();
    res.render('dashboard', { machines, activeAlerts });
  } catch (err) {
    console.error('[frontend] failed to load initial state:', err.message);
    res.render('dashboard', { machines: [], activeAlerts: [] });
  }
});

app.get('/api/history', async (req, res) => {
  const { machine_id, sensor, range } = req.query;
  try {
    const params = new URLSearchParams({ machine_id, sensor, range: range || '1h' });
    const backendRes = await fetch(`${BACKEND_URL}/telemetry/history?${params}`);
    res.status(backendRes.status).json(await backendRes.json());
  } catch (err) {
    res.status(502).json({ error: 'backend unreachable' });
  }
});

app.post('/api/alerts/:id/ack', async (req, res) => {
  try {
    const backendRes = await fetch(`${BACKEND_URL}/alerts/${req.params.id}/acknowledge`, {
      method: 'PATCH',
    });
    res.status(backendRes.status).json(await backendRes.json());
  } catch (err) {
    res.status(502).json({ error: 'backend unreachable' });
  }
});

const server = http.createServer(app);
const wss = new WebSocket.Server({ server, path: '/ws' });
const browserClients = new Set();

wss.on('connection', (ws) => {
  browserClients.add(ws);
  ws.on('close', () => browserClients.delete(ws));
});

function broadcastToBrowsers(message) {
  const payload = JSON.stringify(message);
  for (const ws of browserClients) {
    if (ws.readyState === WebSocket.OPEN) ws.send(payload);
  }
}

function connectUpstream(delay = 1000) {
  const upstream = new WebSocket(BACKEND_WS_URL);
  upstream.on('open', () => console.log('[frontend] connected to backend WS'));
  upstream.on('message', (data) => broadcastToBrowsers(JSON.parse(data.toString())));
  upstream.on('close', () => {
    console.log(`[frontend] backend WS closed, retrying in ${delay}ms`);
    setTimeout(() => connectUpstream(Math.min(delay * 2, 30000)), delay);
  });
  upstream.on('error', () => upstream.close());
}
connectUpstream();

server.listen(PORT, () => console.log(`[frontend] listening on ${PORT}`));
```

- [ ] **Step 3: Create `frontend/views/dashboard.ejs`**

```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>FactorySense — Tableau de bord</title>
  <link rel="stylesheet" href="/style.css">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
</head>
<body>
  <header>
    <h1>FactorySense</h1>
    <span id="connection-status" class="status-pill status-pill--ok">connecté</span>
  </header>

  <main>
    <section id="machines">
      <% machines.forEach(function(m) { %>
        <article class="machine-card status-<%= m.status %>" data-machine-id="<%= m.machine_id %>">
          <h2><%= m.machine_id %></h2>
          <span class="badge badge-<%= m.status %>"><%= m.status %></span>
          <ul class="readings">
            <li>Vibration: <span data-field="vibration"><%= m.latest.vibration %></span> mm/s</li>
            <li>Température: <span data-field="temperature"><%= m.latest.temperature %></span> °C</li>
            <li>Pression: <span data-field="pressure"><%= m.latest.pressure %></span> bar</li>
          </ul>
          <div class="charts">
            <canvas data-chart="vibration" data-machine="<%= m.machine_id %>"></canvas>
            <canvas data-chart="temperature" data-machine="<%= m.machine_id %>"></canvas>
            <canvas data-chart="pressure" data-machine="<%= m.machine_id %>"></canvas>
          </div>
        </article>
      <% }); %>
    </section>

    <section id="alerts">
      <h2>Journal des alertes</h2>
      <ul id="alert-list">
        <% activeAlerts.forEach(function(a) { %>
          <li class="alert alert-<%= a.severity %>" data-alert-id="<%= a.id %>">
            <strong><%= a.machine_id %></strong> — <%= a.sensor %> (<%= a.severity %>) : <%= a.value %>
            <button class="ack-button" data-alert-id="<%= a.id %>">Acquitter</button>
          </li>
        <% }); %>
      </ul>
    </section>
  </main>

  <script>
    window.__INITIAL__ = <%- JSON.stringify({ machines, activeAlerts }) %>;
  </script>
  <script src="/dashboard.js"></script>
</body>
</html>
```

- [ ] **Step 4: Create `frontend/public/dashboard.js`**

```javascript
(function () {
  const initial = window.__INITIAL__ || { machines: [], activeAlerts: [] };
  const charts = {};

  function severityRank(s) {
    return { ok: 0, warning: 1, critical: 2 }[s] ?? 0;
  }

  function setMachineBadge(machineId, status) {
    const card = document.querySelector(`.machine-card[data-machine-id="${machineId}"]`);
    if (!card) return;
    card.className = `machine-card status-${status}`;
    const badge = card.querySelector('.badge');
    badge.className = `badge badge-${status}`;
    badge.textContent = status;
  }

  function bumpMachineStatusIfWorse(machineId, severity) {
    const card = document.querySelector(`.machine-card[data-machine-id="${machineId}"]`);
    if (!card) return;
    const current = card.className.match(/status-(\w+)/)[1];
    if (severityRank(severity) > severityRank(current)) {
      setMachineBadge(machineId, severity);
    }
  }

  function renderNewAlert(alert) {
    const list = document.getElementById('alert-list');
    const li = document.createElement('li');
    li.className = `alert alert-${alert.severity}`;
    li.dataset.alertId = alert.id;
    li.innerHTML = `<strong>${alert.machine_id}</strong> — ${alert.sensor} (${alert.severity}) : ${alert.value}
      <button class="ack-button" data-alert-id="${alert.id}">Acquitter</button>`;
    list.prepend(li);
    bumpMachineStatusIfWorse(alert.machine_id, alert.severity);
  }

  function markAlertAcknowledged(alert) {
    const li = document.querySelector(`li[data-alert-id="${alert.id}"]`);
    if (!li) return;
    li.classList.add('acknowledged');
    const button = li.querySelector('.ack-button');
    if (button) button.remove();
  }

  async function acknowledgeAlert(alertId) {
    await fetch(`/api/alerts/${alertId}/ack`, { method: 'POST' });
  }

  document.addEventListener('click', (event) => {
    if (event.target.classList.contains('ack-button')) {
      acknowledgeAlert(event.target.dataset.alertId);
    }
  });

  function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/ws`);
    const pill = document.getElementById('connection-status');

    ws.onopen = () => {
      pill.textContent = 'connecté';
      pill.className = 'status-pill status-pill--ok';
    };
    ws.onclose = () => {
      pill.textContent = 'reconnexion...';
      pill.className = 'status-pill status-pill--warn';
      setTimeout(connectWebSocket, 2000);
    };
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'alert_new') renderNewAlert(msg.alert);
      if (msg.type === 'alert_ack') markAlertAcknowledged(msg.alert);
    };
  }

  async function loadChart(machineId, sensor) {
    const canvas = document.querySelector(`canvas[data-chart="${sensor}"][data-machine="${machineId}"]`);
    if (!canvas) return;
    const res = await fetch(`/api/history?machine_id=${encodeURIComponent(machineId)}&sensor=${sensor}&range=1h`);
    const points = await res.json();
    charts[`${machineId}-${sensor}`] = new Chart(canvas, {
      type: 'line',
      data: {
        labels: points.map((p) => new Date(p.timestamp).toLocaleTimeString()),
        datasets: [{ label: sensor, data: points.map((p) => p.value), borderWidth: 1, pointRadius: 0 }],
      },
      options: { animation: false, scales: { x: { display: false } } },
    });
  }

  initial.machines.forEach((m) => {
    ['vibration', 'temperature', 'pressure'].forEach((sensor) => loadChart(m.machine_id, sensor));
  });

  connectWebSocket();
})();
```

- [ ] **Step 5: Create `frontend/public/style.css`**

```css
:root {
  --bg: #14181d;
  --panel: #1d232b;
  --text: #e6e9ef;
  --muted: #8b93a1;
  --ok: #2fbf71;
  --warning: #f0a63a;
  --critical: #e5484d;
  --accent: #4da3ff;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: 'Segoe UI', system-ui, sans-serif;
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 2rem;
  background: var(--panel);
  border-bottom: 1px solid #2a313b;
}

header h1 { margin: 0; letter-spacing: 0.05em; color: var(--accent); }

.status-pill { padding: 0.25rem 0.75rem; border-radius: 999px; font-size: 0.8rem; text-transform: uppercase; }
.status-pill--ok { background: rgba(47, 191, 113, 0.15); color: var(--ok); }
.status-pill--warn { background: rgba(240, 166, 58, 0.15); color: var(--warning); }

main { padding: 2rem; display: grid; grid-template-columns: 2fr 1fr; gap: 2rem; }

#machines { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }

.machine-card { background: var(--panel); border-radius: 8px; padding: 1rem; border-left: 4px solid var(--ok); }
.machine-card.status-warning { border-left-color: var(--warning); }
.machine-card.status-critical { border-left-color: var(--critical); }

.badge { display: inline-block; padding: 0.15rem 0.6rem; border-radius: 4px; font-size: 0.75rem; text-transform: uppercase; }
.badge-ok { background: var(--ok); color: #082b17; }
.badge-warning { background: var(--warning); color: #2b1c00; }
.badge-critical { background: var(--critical); color: #2b0405; }

.readings { list-style: none; padding: 0; margin: 0.75rem 0; color: var(--muted); }

.charts { display: grid; grid-template-columns: 1fr; gap: 0.5rem; }
.charts canvas { max-height: 100px; }

#alerts { background: var(--panel); border-radius: 8px; padding: 1rem; height: fit-content; }
#alert-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }

.alert { padding: 0.5rem; border-radius: 6px; background: #262d37; font-size: 0.85rem; }
.alert-warning { border-left: 3px solid var(--warning); }
.alert-critical { border-left: 3px solid var(--critical); }
.alert.acknowledged { opacity: 0.5; }

.ack-button {
  margin-left: 0.5rem;
  background: var(--accent);
  border: none;
  color: #06121f;
  padding: 0.2rem 0.6rem;
  border-radius: 4px;
  cursor: pointer;
}
```

- [ ] **Step 6: Create `frontend/Dockerfile` and `frontend/.dockerignore`**

`frontend/Dockerfile`:
```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
EXPOSE 3000
CMD ["node", "server.js"]
```

`frontend/.dockerignore`:
```
node_modules
```

- [ ] **Step 7: Modify `docker-compose.yml` — add the `frontend` service**

Add under `services:` (after `sensor-simulator`):

```yaml
  frontend:
    build: ./frontend
    environment:
      BACKEND_URL: http://backend:8000
      BACKEND_WS_URL: ws://backend:8000/ws/alerts
      PORT: "3000"
    depends_on:
      backend:
        condition: service_healthy
    ports:
      - "3000:3000"
```

- [ ] **Step 8: Install deps locally (to generate `package-lock.json`), then build and start**

```bash
cd frontend
npm install
cd ..
docker compose up -d --build frontend
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/
```
Expected: `200`.

- [ ] **Step 9: Write the integration test — `frontend/test/ws-relay.test.js`**

```javascript
const assert = require('assert');
const WebSocket = require('ws');

const FRONTEND_WS = process.env.FRONTEND_WS || 'ws://localhost:3000/ws';
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

function postTelemetry(payload) {
  return fetch(`${BACKEND_URL}/telemetry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

async function main() {
  const ws = new WebSocket(FRONTEND_WS);
  await new Promise((resolve, reject) => {
    ws.on('open', resolve);
    ws.on('error', reject);
  });

  const messagePromise = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('timed out waiting for alert_new')), 10000);
    ws.on('message', (data) => {
      const msg = JSON.parse(data.toString());
      if (msg.type === 'alert_new') {
        clearTimeout(timeout);
        resolve(msg);
      }
    });
  });

  const machineId = `ws-test-${Date.now()}`;
  const res = await postTelemetry({
    machine_id: machineId,
    timestamp: new Date().toISOString(),
    vibration: 7.0,
    temperature: 45.0,
    pressure: 5.0,
  });
  assert.strictEqual(res.status, 201, 'expected telemetry POST to succeed');

  const msg = await messagePromise;
  assert.strictEqual(msg.alert.machine_id, machineId);
  assert.strictEqual(msg.alert.severity, 'critical');

  ws.close();
  console.log('OK: frontend relayed alert_new over WebSocket');
}

main().catch((err) => {
  console.error('FAIL:', err.message);
  process.exit(1);
});
```

- [ ] **Step 10: Run the integration test against the live stack**

```bash
docker compose exec -e BACKEND_URL=http://backend:8000 frontend node test/ws-relay.test.js
```
Expected: prints `OK: frontend relayed alert_new over WebSocket`, exit code 0.

- [ ] **Step 11: Commit**

```bash
git add frontend/ docker-compose.yml
git commit -m "feat(frontend): add Node/Express BFF dashboard with live alerts and history charts"
```

---

### Task 8: Scalability demo + final README

**Files:**
- Modify: `README.md`
- Modify: `.gitignore` (verify it still covers everything; extend if needed)

**Interfaces:**
- Consumes: the full running stack from Tasks 1–7.
- Produces: no new code — this task is verification + documentation only.

- [ ] **Step 1: Bring up the full stack and confirm all services are healthy**

```bash
docker compose up -d --build
docker compose ps
```
Expected: `influxdb`, `backend` show `healthy`; `sensor-simulator`, `frontend` show `running` (they have no healthcheck defined).

- [ ] **Step 2: Run the scalability demo**

```bash
docker compose up -d --scale sensor-simulator=3
sleep 10
python3 -c "
import requests
data = requests.get('http://localhost:8000/machines').json()
ids = sorted(m['machine_id'] for m in data)
assert len(ids) == 9, f'expected 9 machines (3 replicas x 3), got {len(ids)}: {ids}'
print('OK:', ids)
"
```
Expected: prints `OK:` followed by 9 distinct machine IDs (no collisions across replicas).

- [ ] **Step 3: Scale back down for a predictable demo state**

```bash
docker compose up -d --scale sensor-simulator=1
```

- [ ] **Step 4: Re-run the full test suite to confirm nothing broke**

```bash
cd backend && python -m pytest tests/ -v && cd ..
docker compose exec -e BACKEND_URL=http://backend:8000 frontend node test/ws-relay.test.js
```
Expected: all backend tests PASS; the WS relay test prints `OK`.

- [ ] **Step 5: Write the final `README.md`**

```markdown
# FactorySense — Prototype de surveillance IoT industrielle

Prototype Docker Compose : simulateur de capteurs → backend FastAPI (InfluxDB + SQLite) → dashboard Node.js.
Conception complète : `docs/superpowers/specs/2026-09-22-factorysense-design.md`.

## Services

| Service | Rôle | Port host |
|---|---|---|
| influxdb | Stockage des séries temporelles (télémétrie) | 8086 |
| backend | API FastAPI, détection de seuils, alertes (SQLite), WebSocket | 8000 |
| sensor-simulator | Génère 3 machines simulées, une en dérive progressive | — |
| frontend | Dashboard Node/Express (BFF), relaie REST + WebSocket vers le backend | 3000 |

## Démarrage

\`\`\`bash
cp .env.example .env
docker compose up -d --build
\`\`\`

Dashboard : http://localhost:3000

## Tests

\`\`\`bash
# unitaires + intégration backend (nécessite la stack lancée)
cd backend
pip install -r requirements-dev.txt
python -m pytest tests/ -v

# relais WebSocket frontend (nécessite la stack lancée)
docker compose exec -e BACKEND_URL=http://backend:8000 frontend node test/ws-relay.test.js
\`\`\`

## Scalabilité

\`\`\`bash
docker compose up -d --scale sensor-simulator=3
\`\`\`

Chaque réplique du simulateur génère 3 machines avec un \`machine_id\` unique dérivé du hostname du conteneur — aucune collision. Vérifier :

\`\`\`bash
curl -s http://localhost:8000/machines | python3 -m json.tool
\`\`\`

Revenir à l'état initial :

\`\`\`bash
docker compose up -d --scale sensor-simulator=1
\`\`\`

## Limites connues

- Le port 8000 du backend est publié côté host uniquement pour les tests automatisés et le débogage ; dans un vrai déploiement il ne serait pas exposé directement.
- Pas d'authentification utilisateur sur le dashboard (hors périmètre du prototype).
- Scaler le service \`backend\` n'est pas démontré (nécessiterait un load balancer devant, hors scope).
- Pas de TLS entre services, pas de chiffrement au repos (hors scope prototype, voir la spec section 7).
- Une alerte reste active jusqu'à acquittement manuel, même si la mesure revient à la normale (choix assumé pour la traçabilité).
```

- [ ] **Step 6: Commit**

```bash
git add README.md .gitignore
git commit -m "docs: add full README with setup, testing, and scalability instructions"
```
