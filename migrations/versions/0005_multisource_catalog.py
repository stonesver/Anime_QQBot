"""Multisource catalog: internal anime identity, source links and snapshots.

Adds:

* animes - internal Anime records with display fields and NSFW provenance
* external_entries - one row per (provider, external_id)
* anime_source_links - audited links between an Anime and an External Entry
* source_snapshots - versioned, timestamped payload snapshots
* anime_titles - canonicalised multi-language titles per Anime
* airing_occurrences - dated / precisely-timed airing events per Anime
* source_sync_states - per-provider last success / failure cursor

Keeps anime_subjects / airing_schedules / catalog_sync_states for now;
the migration leaves v0.1 tables untouched so Task 27 can drop them on
its own schedule. Downgrade only removes the new tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_multisource_catalog"
down_revision: str | None = "0004_schedules_and_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NSFW_FLAG_VALUES = ("true", "false", "unknown")
LINK_STATUS_VALUES = ("confirmed", "probable", "unresolved", "rejected")
EVIDENCE_TYPE_VALUES = (
    "manual",
    "cross_id",
    "mikan_bangumi_link",
    "title_season_year",
    "title_fuzzy",
)
AIRING_PRECISION_VALUES = ("exact", "date_only")


def upgrade() -> None:
    op.create_table(
        "animes",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("nsfw_flag", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("display_title", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            f"nsfw_flag IN {NSFW_FLAG_VALUES!r}",
            name="ck_animes_nsfw_flag",
        ),
    )

    op.create_table(
        "external_entries",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "provider",
            "external_id",
            name="uq_external_entries_provider_external_id",
        ),
    )
    op.create_index("ix_external_entries_provider", "external_entries", ["provider"])

    op.create_table(
        "anime_source_links",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "anime_id",
            postgresql.UUID(),
            sa.ForeignKey("animes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "external_entry_id",
            postgresql.UUID(),
            sa.ForeignKey("external_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="unresolved"),
        sa.Column("evidence_type", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(64), nullable=True),
        sa.UniqueConstraint(
            "anime_id",
            "external_entry_id",
            name="uq_anime_source_links_anime_entry",
        ),
        sa.CheckConstraint(
            f"status IN {LINK_STATUS_VALUES!r}",
            name="ck_anime_source_links_status",
        ),
        sa.CheckConstraint(
            f"evidence_type IN {EVIDENCE_TYPE_VALUES!r}",
            name="ck_anime_source_links_evidence_type",
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_anime_source_links_confidence",
        ),
    )
    op.create_index(
        "ix_anime_source_links_external_entry",
        "anime_source_links",
        ["external_entry_id"],
    )

    op.create_table(
        "source_snapshots",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "external_entry_id",
            postgresql.UUID(),
            sa.ForeignKey("external_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "external_entry_id",
            "version",
            name="uq_source_snapshots_entry_version",
        ),
        sa.CheckConstraint("version >= 1", name="ck_source_snapshots_version_positive"),
    )
    op.create_index(
        "ix_source_snapshots_fetched_at",
        "source_snapshots",
        ["fetched_at"],
    )

    op.create_table(
        "anime_titles",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "anime_id",
            postgresql.UUID(),
            sa.ForeignKey("animes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("is_alias", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "anime_id", "language", "title", name="uq_anime_titles_anime_lang_title"
        ),
    )

    op.create_table(
        "airing_occurrences",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "anime_id",
            postgresql.UUID(),
            sa.ForeignKey("animes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_entry_id",
            postgresql.UUID(),
            sa.ForeignKey("external_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("episode_label", sa.String(64), nullable=False),
        sa.Column("air_date", sa.Date(), nullable=False),
        sa.Column("air_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("precision", sa.String(16), nullable=False),
        sa.Column("source_event_key", sa.String(192), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_entry_id", "source_event_key", name="uq_airing_occurrences_event"
        ),
        sa.CheckConstraint(
            f"precision IN {AIRING_PRECISION_VALUES!r}",
            name="ck_airing_occurrences_precision",
        ),
    )
    op.create_index(
        "ix_airing_occurrences_air_date",
        "airing_occurrences",
        ["air_date"],
    )
    op.create_index(
        "ix_airing_occurrences_anime_id",
        "airing_occurrences",
        ["anime_id"],
    )

    op.create_table(
        "source_sync_states",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_cursor", sa.String(192), nullable=True),
        sa.Column("rate_limit_remaining", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("source_sync_states")
    op.drop_index("ix_airing_occurrences_anime_id", table_name="airing_occurrences")
    op.drop_index("ix_airing_occurrences_air_date", table_name="airing_occurrences")
    op.drop_table("airing_occurrences")
    op.drop_table("anime_titles")
    op.drop_index("ix_source_snapshots_fetched_at", table_name="source_snapshots")
    op.drop_table("source_snapshots")
    op.drop_index("ix_anime_source_links_external_entry", table_name="anime_source_links")
    op.drop_table("anime_source_links")
    op.drop_index("ix_external_entries_provider", table_name="external_entries")
    op.drop_table("external_entries")
    op.drop_table("animes")
