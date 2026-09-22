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


def query_machine_ids(client, window="10m"):
    # Deviation from the originally suggested implementation: schema.tagValues()
    # does not honor `start` against this bucket's shard-group duration (168h) —
    # it returns every machine_id ever written to the current shard regardless of
    # the window, verified empirically. Filtering the actual measurement data by
    # range and taking distinct machine_ids gives the correct time-bounded result.
    flux = f'''
    from(bucket: "{config.INFLUX_BUCKET}")
      |> range(start: -{window})
      |> filter(fn: (r) => r._measurement == "telemetry")
      |> keep(columns: ["machine_id"])
      |> distinct(column: "machine_id")
    '''
    tables = client.query_api().query(flux, org=config.INFLUX_ORG)
    return list({record.get_value() for table in tables for record in table.records})


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
