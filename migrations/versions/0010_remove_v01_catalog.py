"""Remove v0.1 catalog compatibility tables (Task 27).

Drops: anime_subjects, airing_schedules, catalog_sync_states.
New tables (animes, airing_occurrences, source_sync_states) are NOT
affected. Downgrade restores empty table structures without data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_remove_v01_catalog"
down_revision: str | None = "0009_resource_releases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("catalog_sync_states")
    op.drop_index("ix_airing_schedules_air_date", table_name="airing_schedules")
    op.drop_table("airing_schedules")
    op.drop_index("ix_anime_subjects_air_date", table_name="anime_subjects")
    op.drop_table("anime_subjects")


def downgrade() -> None:
    op.create_table(
        "anime_subjects",
        sa.Column("subject_id", sa.BigInteger(), primary_key=True),
        sa.Column("title_cn", sa.String(512), nullable=True),
        sa.Column("title_jp", sa.String(512), nullable=False),
        sa.Column("air_date", sa.Date(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("total_episodes", sa.Integer(), nullable=True),
        sa.Column("nsfw", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_anime_subjects_air_date", "anime_subjects", ["air_date"])
    op.create_table(
        "airing_schedules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "subject_id",
            sa.BigInteger(),
            sa.ForeignKey("anime_subjects.subject_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occurrence_key", sa.String(192), nullable=False),
        sa.Column("air_date", sa.Date(), nullable=False),
        sa.Column("air_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("episode", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_airing_schedules_air_date", "airing_schedules", ["air_date"])
    op.create_table(
        "catalog_sync_states",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
