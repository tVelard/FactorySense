import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def conn():
    """Connection to the stack's Postgres; everything a test writes is rolled back."""
    import psycopg
    from psycopg.rows import dict_row

    dsn = (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@localhost:5432/{os.environ['POSTGRES_DB']}"
    )
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        yield connection
        connection.rollback()
