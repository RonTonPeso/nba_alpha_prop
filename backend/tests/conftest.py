"""
DB-backed tests use a transaction rollback defense thing against the dev
database so every test runs inside an outer transaction that's rolled
back on teardown, so no test messes with the shared state. If Postgres isn't
reachable, DB-backed tests are skipped with db_engine
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import delete
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.db.engine import get_engine
from app.db.tables import (
    Game,
    GameResult,
    KalshiPlayerAlias,
    Market,
    MarketSettlement,
    MarketSnapshot,
    Player,
    PlayerGameLog,
    RequestCache,
    Team,
)


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

    Inside the transaction, every fact and identity table is cleared so
    tests see an empty DB regardless of what real bulk-loaded data lives
    in the dev DB. The fixture rolls back on teardown, so the real data
    is restored as if the test never ran.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    # Wipe in FK-safe order. All deletes are part of the outer transaction
    # and are undone by the rollback in the finally block below.
    for table in (
        MarketSnapshot,
        MarketSettlement,
        Market,
        KalshiPlayerAlias,
        PlayerGameLog,
        GameResult,
        Game,
        Player,
        Team,
        RequestCache,
    ):
        session.execute(delete(table))
    session.flush()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
