import os
import time

import requests

BASE_URL = "http://localhost:8000"
AUTH = {"X-API-Key": os.environ.get("SENSOR_API_KEY", "")}


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
    resp = requests.post(f"{BASE_URL}/telemetry", json=payload, headers=AUTH, timeout=5)
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
    resp = requests.post(f"{BASE_URL}/telemetry", json=payload, headers=AUTH, timeout=5)
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


def test_telemetry_without_valid_api_key_is_rejected():
    payload = {
        "machine_id": _unique_machine_id(),
        "timestamp": "2026-01-01T00:00:00Z",
        "vibration": 2.0,
        "temperature": 45.0,
        "pressure": 5.0,
    }
    for headers in ({}, {"X-API-Key": "wrong"}):
        resp = requests.post(f"{BASE_URL}/telemetry", json=payload, headers=headers, timeout=5)
        assert resp.status_code == 401
