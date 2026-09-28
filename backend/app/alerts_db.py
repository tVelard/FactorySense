import json
from datetime import datetime, timezone

import psycopg

# Functions take an open connection and never commit: the caller owns the
# transaction (pool.connection() commits on exit), so NOTIFY is only delivered
# once the alert change is committed.


def get_active_alert(conn: psycopg.Connection, machine_id: str, sensor: str) -> dict | None:
    return conn.execute(
        "SELECT * FROM alerts WHERE machine_id = %s AND sensor = %s AND status = 'active' "
        "ORDER BY raised_at DESC LIMIT 1",
        (machine_id, sensor),
    ).fetchone()


def get_alert_by_id(conn: psycopg.Connection, alert_id: int) -> dict | None:
    return conn.execute("SELECT * FROM alerts WHERE id = %s", (alert_id,)).fetchone()


def create_alert(
    conn: psycopg.Connection,
    machine_id: str,
    sensor: str,
    severity: str,
    value: float,
    threshold: float,
) -> dict:
    raised_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE alerts SET status = 'superseded' WHERE machine_id = %s AND sensor = %s AND status = 'active'",
        (machine_id, sensor),
    )
    return conn.execute(
        "INSERT INTO alerts (machine_id, sensor, severity, value, threshold, raised_at, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'active') RETURNING *",
        (machine_id, sensor, severity, value, threshold, raised_at),
    ).fetchone()


def list_alerts(
    conn: psycopg.Connection, status: str | None = None, machine_id: str | None = None
) -> list[dict]:
    query = "SELECT * FROM alerts WHERE 1=1"
    params: list[str] = []
    if status:
        query += " AND status = %s"
        params.append(status)
    if machine_id:
        query += " AND machine_id = %s"
        params.append(machine_id)
    query += " ORDER BY raised_at DESC"
    return conn.execute(query, params).fetchall()


def acknowledge_alert(conn: psycopg.Connection, alert_id: int) -> dict | None:
    acknowledged_at = datetime.now(timezone.utc).isoformat()
    return conn.execute(
        "UPDATE alerts SET status = 'acknowledged', acknowledged_at = %s "
        "WHERE id = %s AND status <> 'acknowledged' RETURNING *",
        (acknowledged_at, alert_id),
    ).fetchone()


def notify(conn: psycopg.Connection, message: dict) -> None:
    # Every backend replica LISTENs on this channel and relays to its own WebSocket clients.
    conn.execute("SELECT pg_notify('alerts', %s)", (json.dumps(message),))
