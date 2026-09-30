import os

THRESHOLDS = {
    "vibration": {"warning": 4.0, "critical": 6.0, "unit": "mm/s"},
    "temperature": {"warning": 70.0, "critical": 85.0, "unit": "°C"},
    "pressure": {"warning": 8.0, "critical": 10.0, "unit": "bar"},
}

INFLUX_URL = os.environ.get("INFLUX_URL", "http://telemetry-db:8086")
INFLUX_TOKEN = os.environ.get("INFLUX_TOKEN", "")
INFLUX_ORG = os.environ.get("INFLUX_ORG", "factorysense")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "telemetry")
SENSOR_API_KEY = os.environ.get("SENSOR_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
