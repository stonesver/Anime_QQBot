"""Add low-frequency weekly, daily and poll content operations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_content_operations"
down_revision: str | None = "0015_anilist_mapping_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "group_runtime_settings",
        sa.Column("weekly_report_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "group_runtime_settings",
        sa.Column("weekly_report_weekday", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "group_runtime_settings",
        sa.Column("weekly_report_minute", sa.Integer(), nullable=False, server_default="1200"),
    )
    op.add_column(
        "group_runtime_settings",
        sa.Column("daily_digest_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "group_runtime_settings",
        sa.Column(
            "daily_digest_at_all_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "group_runtime_settings",
        sa.Column(
            "daily_digest_anchor_minute", sa.Integer(), nullable=False, server_default="1350"
        ),
    )
    op.add_column(
        "group_runtime_settings",
        sa.Column("daily_digest_quiet_minutes", sa.Integer(), nullable=False, server_default="20"),
    )
    op.add_column(
        "group_runtime_settings",
        sa.Column(
            "daily_digest_cutoff_minute", sa.Integer(), nullable=False, server_default="1410"
        ),
    )
    op.create_check_constraint(
        "ck_group_runtime_settings_weekly_weekday",
        "group_runtime_settings",
        "weekly_report_weekday BETWEEN 0 AND 6",
    )
    op.create_check_constraint(
        "ck_group_runtime_settings_weekly_minute",
        "group_runtime_settings",
        "weekly_report_minute BETWEEN 0 AND 1439",
    )
    op.create_check_constraint(
        "ck_group_runtime_settings_digest_window",
        "group_runtime_settings",
        "daily_digest_anchor_minute >= 0 AND "
        "daily_digest_anchor_minute < daily_digest_cutoff_minute AND "
        "daily_digest_cutoff_minute <= 1439",
    )
    op.create_check_constraint(
        "ck_group_runtime_settings_digest_quiet",
        "group_runtime_settings",
        "daily_digest_quiet_minutes >= 1 AND "
        "daily_digest_quiet_minutes <= "
        "daily_digest_cutoff_minute - daily_digest_anchor_minute",
    )

    op.create_table(
        "content_publications",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "chat_group_id",
            postgresql.UUID(),
            sa.ForeignKey("chat_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("publication_type", sa.String(32), nullable=False),
        sa.Column("period_key", sa.String(128), nullable=False),
        sa.Column(
            "notification_job_id",
            postgresql.UUID(),
            sa.ForeignKey("notification_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("platform_message_id", sa.String(192), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="planned"),
        sa.Column("essence_status", sa.String(16), nullable=False, server_default="none"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "publication_type IN "
            "('weekly_report', 'daily_release_digest', 'poll_open', 'poll_result')",
            name="ck_content_publications_type",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'sent', 'failed', 'unknown')",
            name="ck_content_publications_status",
        ),
        sa.CheckConstraint(
            "essence_status IN ('none', 'set', 'failed', 'removed')",
            name="ck_content_publications_essence",
        ),
        sa.UniqueConstraint(
            "chat_group_id",
            "publication_type",
            "period_key",
            name="uq_content_publications_period",
        ),
    )
    op.create_table(
        "content_polls",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "chat_group_id",
            postgresql.UUID(),
            sa.ForeignKey("chat_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("theme", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("period_key", sa.String(128), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "theme IN ('weekly_best', 'next_week_anticipated', 'season_favorite', 'group_watch')",
            name="ck_content_polls_theme",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'open', 'closed', 'cancelled')",
            name="ck_content_polls_status",
        ),
        sa.CheckConstraint("closes_at > opens_at", name="ck_content_polls_window"),
        sa.UniqueConstraint("chat_group_id", "period_key", name="uq_content_polls_period"),
    )
    op.create_table(
        "content_poll_candidates",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "poll_id",
            postgresql.UUID(),
            sa.ForeignKey("content_polls.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "anime_id",
            postgresql.UUID(),
            sa.ForeignKey("animes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position BETWEEN 1 AND 6", name="ck_content_poll_candidates_position"),
        sa.UniqueConstraint("poll_id", "anime_id", name="uq_content_poll_candidates_anime"),
        sa.UniqueConstraint("poll_id", "position", name="uq_content_poll_candidates_position"),
    )
    op.create_table(
        "content_poll_votes",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "poll_id",
            postgresql.UUID(),
            sa.ForeignKey("content_polls.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            postgresql.UUID(),
            sa.ForeignKey("content_poll_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_user_id", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("poll_id", "external_user_id", name="uq_content_poll_votes_user"),
    )


def downgrade() -> None:
    op.drop_table("content_poll_votes")
    op.drop_table("content_poll_candidates")
    op.drop_table("content_polls")
    op.drop_table("content_publications")
    op.drop_constraint(
        "ck_group_runtime_settings_digest_quiet", "group_runtime_settings", type_="check"
    )
    op.drop_constraint(
        "ck_group_runtime_settings_digest_window", "group_runtime_settings", type_="check"
    )
    op.drop_constraint(
        "ck_group_runtime_settings_weekly_minute", "group_runtime_settings", type_="check"
    )
    op.drop_constraint(
        "ck_group_runtime_settings_weekly_weekday", "group_runtime_settings", type_="check"
    )
    op.drop_column("group_runtime_settings", "daily_digest_cutoff_minute")
    op.drop_column("group_runtime_settings", "daily_digest_quiet_minutes")
    op.drop_column("group_runtime_settings", "daily_digest_anchor_minute")
    op.drop_column("group_runtime_settings", "daily_digest_at_all_enabled")
    op.drop_column("group_runtime_settings", "daily_digest_enabled")
    op.drop_column("group_runtime_settings", "weekly_report_minute")
    op.drop_column("group_runtime_settings", "weekly_report_weekday")
    op.drop_column("group_runtime_settings", "weekly_report_enabled")
