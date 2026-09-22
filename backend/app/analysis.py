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
