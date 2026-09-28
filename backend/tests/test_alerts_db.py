from app import alerts_db


def test_get_active_alert_returns_none_when_no_alerts(conn):
    assert alerts_db.get_active_alert(conn, "machine-1", "vibration") is None


def test_create_alert_returns_active_alert_with_expected_fields(conn):
    alert = alerts_db.create_alert(conn, "machine-1", "vibration", "warning", 4.5, 4.0)
    assert alert["machine_id"] == "machine-1"
    assert alert["sensor"] == "vibration"
    assert alert["severity"] == "warning"
    assert alert["status"] == "active"
    assert alert["acknowledged_at"] is None
    assert alert["id"] is not None


def test_get_active_alert_finds_most_recent_active_alert(conn):
    first = alerts_db.create_alert(conn, "machine-1", "vibration", "warning", 4.5, 4.0)
    second = alerts_db.create_alert(conn, "machine-1", "vibration", "critical", 6.5, 6.0)
    active = alerts_db.get_active_alert(conn, "machine-1", "vibration")
    assert active["id"] == second["id"]
    assert active["severity"] == "critical"

    # the escalation should supersede the earlier alert rather than leaving
    # two "active" rows for the same machine/sensor
    superseded = alerts_db.get_alert_by_id(conn, first["id"])
    assert superseded["status"] == "superseded"

def test_list_alerts_filters_by_status_and_machine(conn):
    a1 = alerts_db.create_alert(conn, "machine-1", "vibration", "warning", 4.5, 4.0)
    alerts_db.create_alert(conn, "machine-2", "temperature", "critical", 90.0, 85.0)
    alerts_db.acknowledge_alert(conn, a1["id"])

    assert alerts_db.list_alerts(conn, status="active", machine_id="machine-1") == []
    active = alerts_db.list_alerts(conn, status="active", machine_id="machine-2")
    assert len(active) == 1
    assert active[0]["sensor"] == "temperature"

    machine1_alerts = alerts_db.list_alerts(conn, machine_id="machine-1")
    assert len(machine1_alerts) == 1
    assert machine1_alerts[0]["status"] == "acknowledged"


def test_acknowledge_alert_sets_status_and_timestamp(conn):
    alert = alerts_db.create_alert(conn, "machine-1", "vibration", "warning", 4.5, 4.0)
    acknowledged = alerts_db.acknowledge_alert(conn, alert["id"])
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["acknowledged_at"] is not None


def test_acknowledge_alert_returns_none_for_unknown_id(conn):
    assert alerts_db.acknowledge_alert(conn, -1) is None


def test_acknowledge_alert_returns_none_if_already_acknowledged(conn):
    alert = alerts_db.create_alert(conn, "machine-1", "vibration", "warning", 4.5, 4.0)
    alerts_db.acknowledge_alert(conn, alert["id"])
    assert alerts_db.acknowledge_alert(conn, alert["id"]) is None
