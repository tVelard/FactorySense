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
    conn.execute(
        "UPDATE alerts SET status = 'superseded' WHERE machine_id = ? AND sensor = ? AND status = 'active'",
        (machine_id, sensor),
    )
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
