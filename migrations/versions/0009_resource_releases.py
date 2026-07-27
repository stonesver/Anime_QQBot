"""Mikan resource releases and release batches (Task 21)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_resource_releases"
down_revision: str | None = "0008_following_and_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resource_releases",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("mikan_item_id", sa.String(128), nullable=False),
        sa.Column("content_fingerprint", sa.String(128), nullable=False, unique=True),
        sa.Column("raw_title", sa.String(512), nullable=False),
        sa.Column("pub_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=True),
        sa.Column("episode_label", sa.String(64), nullable=True),
        sa.Column("subtitle_groups", postgresql.ARRAY(sa.String(64)), server_default="{}"),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("resolutions", postgresql.ARRAY(sa.String(16)), server_default="{}"),
        sa.Column("anime_id", postgresql.UUID(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("mikan_item_id", name="uq_resource_releases_item_id"),
    )

    op.create_table(
        "release_batches",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("anime_id", postgresql.UUID(), sa.ForeignKey("animes.id"), nullable=True),
        sa.Column("episode_label", sa.String(64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.UniqueConstraint("anime_id", "episode_label", "window_started_at", name="uq_release_batches_key"),
    )


def downgrade() -> None:
    op.drop_table("release_batches")
    op.drop_table("resource_releases")