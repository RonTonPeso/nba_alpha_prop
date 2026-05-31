"""Database engine and FastAPI session dependency.

DATABASE_URL is read from the environment. In local dev, set it in `.env`
at the repo root (copy from `.env.example`). In Docker/Railway, it's set
as a real env var and the .env loader is a no-op.
"""

import os
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

# Load .env from repo root once at import time. No-op when the var is
# already set by the surrounding environment.
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


def _normalize_url(url: str) -> str:
    # Older Postgres URLs (Heroku-era, sometimes Railway) use postgres://.
    # SQLAlchemy 2.x wants postgresql://, and we want the +psycopg driver
    # explicitly because that's what we installed.
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def _build_engine() -> Engine:
    url = os.environ.get("DATABASE_URL")
    if url is None:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and fill it in, "
            "or set the env var directly."
        )
    return create_engine(_normalize_url(url), echo=False, pool_pre_ping=True)


_engine: Engine | None = None


def get_engine() -> Engine:
    # Lazy so importing this module doesn't require DATABASE_URL. Tests
    # that don't touch the DB can skip the env var.
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding one Session per request."""
    with Session(get_engine()) as session:
        yield session
