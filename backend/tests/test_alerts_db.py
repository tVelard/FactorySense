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
