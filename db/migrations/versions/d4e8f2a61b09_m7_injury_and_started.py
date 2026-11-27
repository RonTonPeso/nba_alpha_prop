"""m7 injury_signals and player_game_logs.started

Revision ID: d4e8f2a61b09
Revises: b7c2e9a41d08
Create Date: 2026-11-27 01:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d4e8f2a61b09"
down_revision: str | Sequence[str] | None = "b7c2e9a41d08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "player_game_logs",
        sa.Column("started", sa.Boolean(), nullable=True),
    )
    op.create_table(
        "injury_signals",
        sa.Column("injury_signal_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=True),
        sa.Column("player_name_raw", sa.String(), nullable=False),
        sa.Column("claim_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=True),
        sa.Column("expected_games_missed", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_reliability_prior", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("raw_text", sa.String(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("classifier_model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column(
            "raw_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["player_id"], ["players.player_id"]),
        sa.PrimaryKeyConstraint("injury_signal_id"),
    )
    op.create_index(
        "ix_injury_signals_event_available",
        "injury_signals",
        ["event_time", "available_at"],
    )
    op.create_index(
        "ix_injury_signals_player_event",
        "injury_signals",
        ["player_id", "event_time"],
    )
    op.create_index(
        "ix_injury_signals_source_url",
        "injury_signals",
        ["source_url"],
    )


def downgrade() -> None:
    op.drop_index("ix_injury_signals_source_url", table_name="injury_signals")
    op.drop_index("ix_injury_signals_player_event", table_name="injury_signals")
    op.drop_index("ix_injury_signals_event_available", table_name="injury_signals")
    op.drop_table("injury_signals")
    op.drop_column("player_game_logs", "started")
