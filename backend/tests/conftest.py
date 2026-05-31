"""
DB-backed tests use a transaction rollback defense thing against the dev
database so every test runs inside an outer transaction that's rolled
back on teardown, so no test messes with the shared state. If Postgres isn't
reachable, DB-backed tests are skipped with db_engine
"""

from collections.abc import Iterator

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.db.engine import get_engine


@pytest.fixture(scope="session")
def db_engine() -> Engine:
    """Return engine if Postgres is reachable. Skip test if not."""
    try:
        engine = get_engine()
        with engine.connect():
            pass
    except Exception as exc:
        pytest.skip(f"Postgres unavailable, skipping DB tests: {exc}")
    return engine


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Yield a Session bound to a connection wrapped in a transaction.
    The fixture rolls back on teardown so each test sees a clean DB
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
