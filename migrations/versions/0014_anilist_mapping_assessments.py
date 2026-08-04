"""Persist strict AniList mapping outcomes for retry scheduling and operations UI."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_anilist_mapping_assessments"
down_revision: str | None = "0013_runtime_component_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "anilist_mapping_assessments",
        sa.Column(
            "anime_id",
            postgresql.UUID(),
            sa.ForeignKey("animes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(128), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("candidate_count >= 0", name="ck_anilist_mapping_assessments_count"),
    )
    op.create_index(
        "ix_anilist_mapping_assessments_retry_after",
        "anilist_mapping_assessments",
        ["retry_after"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_anilist_mapping_assessments_retry_after",
        table_name="anilist_mapping_assessments",
    )
    op.drop_table("anilist_mapping_assessments")
