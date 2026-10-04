-- Run once by the postgres image on an empty volume.
CREATE TABLE alerts (
    id SERIAL PRIMARY KEY,
    machine_id TEXT NOT NULL,
    sensor TEXT NOT NULL,
    severity TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    threshold DOUBLE PRECISION NOT NULL,
    raised_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    acknowledged_at TEXT
);

CREATE UNIQUE INDEX one_active_alert ON alerts (machine_id, sensor) WHERE status = 'active';
