"""box score available_at

Revision ID: b7c2e9a41d08
Revises: c3b1a9e0d4f2
Create Date: 2026-11-07 02:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c2e9a41d08"
down_revision: str | Sequence[str] | None = "c3b1a9e0d4f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKFILL = """
UPDATE {table} AS fact
SET available_at = (
    ((g.game_date + INTERVAL '1 day')::date + TIME '12:00:00') AT TIME ZONE 'UTC'
)
FROM games AS g
WHERE fact.game_id = g.game_id
  AND fact.available_at IS NULL
"""


def upgrade() -> None:
    for table in ("player_game_logs", "game_results"):
        op.add_column(
            table,
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.execute(_BACKFILL.format(table=table))
        op.alter_column(table, "available_at", nullable=False)
    op.create_index(
        "ix_pgl_player_event_available",
        "player_game_logs",
        ["player_id", "event_time", "available_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pgl_player_event_available", table_name="player_game_logs")
    op.drop_column("game_results", "available_at")
    op.drop_column("player_game_logs", "available_at")
