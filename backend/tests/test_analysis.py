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
