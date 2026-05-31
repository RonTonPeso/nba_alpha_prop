import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Make backend/ importable so we can pull in the SQLModel tables.
# env.py lives at <repo>/db/migrations/env.py, so backend/ is two up + sibling.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from sqlmodel import SQLModel  # noqa: E402

from app.db import tables  # noqa: E402, F401  - import for side effects (table registration)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Read DATABASE_URL from env so connection strings stay out of alembic.ini.
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# All SQLModel table classes register themselves on SQLModel.metadata at
# import time. The `tables` import above is what populates it.
target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def _render_item(type_: str, obj: object, _autogen_context: object) -> object:
    """Emit sa.String instead of sqlmodel.sql.sqltypes.AutoString in migrations.

    SQLModel uses AutoString internally for string fields. Rendering it
    literally would require every migration file to import sqlmodel. Plain
    sa.String is functionally identical and keeps migrations sqlmodel-free.
    """
    if type_ == "type" and obj.__class__.__name__ == "AutoString":
        return "sa.String()"
    return False


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=_render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_item=_render_item,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
