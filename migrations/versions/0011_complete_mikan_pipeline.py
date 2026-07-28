"""Complete persistent Mikan polling and release batch state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_complete_mikan_pipeline"
down_revision: str | None = "0010_remove_v01_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mikan_feed_states",
        sa.Column("id", sa.String(192), primary_key=True),
        sa.Column(
            "external_entry_id",
            postgresql.UUID(),
            sa.ForeignKey("external_entries.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("rss_url", sa.Text(), nullable=False),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("last_modified", sa.Text(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column(
        "resource_releases",
        sa.Column("mikan_entry_id", postgresql.UUID(), nullable=True),
    )
    op.add_column(
        "resource_releases",
        sa.Column("parser_version", sa.String(32), nullable=False, server_default="v1"),
    )
    op.create_foreign_key(
        "fk_resource_releases_anime",
        "resource_releases",
        "animes",
        ["anime_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_resource_releases_mikan_entry",
        "resource_releases",
        "external_entries",
        ["mikan_entry_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "release_batch_items",
        sa.Column(
            "batch_id",
            postgresql.UUID(),
            sa.ForeignKey("release_batches.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "release_id",
            postgresql.UUID(),
            sa.ForeignKey("resource_releases.id", ondelete="CASCADE"),
            primary_key=True,
            unique=True,
        ),
    )
    op.alter_column("resource_releases", "parser_version", server_default=None)


def downgrade() -> None:
    op.drop_table("release_batch_items")
    op.drop_constraint(
        "fk_resource_releases_mikan_entry",
        "resource_releases",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_resource_releases_anime",
        "resource_releases",
        type_="foreignkey",
    )
    op.drop_column("resource_releases", "parser_version")
    op.drop_column("resource_releases", "mikan_entry_id")
    op.drop_table("mikan_feed_states")
