"""m3 predictions

Revision ID: c3b1a9e0d4f2
Revises: 124f1a7e317d
Create Date: 2026-11-06 02:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c3b1a9e0d4f2"
down_revision: str | Sequence[str] | None = "124f1a7e317d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "predictions",
        sa.Column("prediction_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.String(), nullable=False),
        sa.Column("prop_type", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("prediction_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("mean", sa.Float(), nullable=False),
        sa.Column("std", sa.Float(), nullable=False),
        sa.Column("quantile_10", sa.Float(), nullable=False),
        sa.Column("quantile_50", sa.Float(), nullable=False),
        sa.Column("quantile_90", sa.Float(), nullable=False),
        sa.Column("n_games", sa.Integer(), nullable=False),
        sa.Column("low_confidence", sa.Boolean(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.game_id"]),
        sa.ForeignKeyConstraint(["player_id"], ["players.player_id"]),
        sa.PrimaryKeyConstraint("prediction_id"),
        sa.UniqueConstraint(
            "player_id",
            "game_id",
            "prop_type",
            "model_version",
            name="uq_predictions_player_game_prop_version",
        ),
    )
    op.create_index("ix_predictions_player_time", "predictions", ["player_id", "prediction_time"])
    op.create_index("ix_predictions_game", "predictions", ["game_id"])


def downgrade() -> None:
    op.drop_index("ix_predictions_game", table_name="predictions")
    op.drop_index("ix_predictions_player_time", table_name="predictions")
    op.drop_table("predictions")
