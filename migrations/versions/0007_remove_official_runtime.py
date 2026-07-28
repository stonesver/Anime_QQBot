"""Remove official QQ bot runtime tables (Task 10).

Drops legacy v0.1 tables that were tied to QQ official bot identity
(group_openid, member_openid, admin identities by openid, and old
delivery/notification/schedule tables). The new chat_groups /
group_memberships tables (0006) are NOT affected.

The downgrade re-creates the exact v0.1 structure as defined by
migrations 0001, 0002, 0003, and 0004 (including primary key
identities, indexes, unique constraints, and check constraints).
Data is not recovered because destructive migrations only discard
business rows; the revision chain itself is preserved.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_remove_official_runtime"
down_revision: str | None = "0006_chat_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Order matters: drop tables with FK dependencies before their parents.
    # Indexes go with their owning tables, so we drop the indexes first.
    op.drop_index("ix_notification_jobs_claim", table_name="notification_jobs")
    op.drop_index("ix_group_schedules_due", table_name="group_schedules")
    op.drop_index("ix_subscriptions_group_enabled", table_name="subscriptions")
    op.drop_table("delivery_attempts")
    op.drop_table("notification_jobs")
    op.drop_table("group_schedules")
    op.drop_table("subscriptions")
    op.drop_table("admin_identities")
    op.drop_table("group_members")
    op.drop_table("groups")
    op.drop_table("processed_events")
    op.drop_table("worker_heartbeats")


def downgrade() -> None:
    # The v0.1 catalog tables (anime_subjects, airing_schedules,
    # catalog_sync_states) are owned by 0002 in the revision chain.
    # 0007's downgrade needs them again because 0010 dropped them; if
    # the chain is partially downgraded already (e.g. after 0010
    # downgrade to 0009 then 0008 then here), the tables may already
    # exist. Drop them first so we can recreate them cleanly.
    op.drop_table("catalog_sync_states")
    op.drop_index("ix_airing_schedules_air_date", table_name="airing_schedules")
    op.drop_table("airing_schedules")
    op.drop_index("ix_anime_subjects_air_date", table_name="anime_subjects")
    op.drop_table("anime_subjects")
    # Mirror the schema produced by 0001+0002+0003+0004 exactly.
    # 0001: groups, group_members, admin_identities, processed_events,
    #       worker_heartbeats.
    op.create_table(
        "groups",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("group_openid", sa.String(128), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Shanghai"),
        sa.Column(
            "active_messages_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("group_openid", name="uq_groups_group_openid"),
    )
    op.create_table(
        "group_members",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "group_id",
            sa.BigInteger(),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("member_openid", sa.String(128), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_group_members_role"),
        sa.UniqueConstraint("group_id", "member_openid", name="uq_group_members_group_member"),
    )
    op.create_table(
        "admin_identities",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("group_openid", sa.String(128), nullable=False),
        sa.Column("member_openid", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("group_openid", "member_openid", name="uq_admin_identities_pair"),
    )
    op.create_table(
        "processed_events",
        sa.Column("platform_event_id", sa.String(192), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(128), primary_key=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # 0002: anime_subjects, airing_schedules, catalog_sync_states.
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
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
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
        sa.UniqueConstraint("occurrence_key", name="uq_airing_schedules_occurrence_key"),
    )
    op.create_index("ix_airing_schedules_air_date", "airing_schedules", ["air_date"])
    op.create_table(
        "catalog_sync_states",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    # 0003: subscriptions.
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "group_id",
            sa.BigInteger(),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("member_openid", sa.String(128), nullable=False),
        sa.Column(
            "subject_id",
            sa.BigInteger(),
            sa.ForeignKey("anime_subjects.subject_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "group_id", "member_openid", "subject_id", name="uq_subscriptions_group_member_subject"
        ),
    )
    op.create_index("ix_subscriptions_group_enabled", "subscriptions", ["group_id", "enabled"])
    # 0004: group_schedules, notification_jobs, delivery_attempts.
    op.create_table(
        "group_schedules",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "group_id",
            sa.BigInteger(),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("schedule_type", sa.String(16), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("local_time", sa.Time(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("schedule_type IN ('daily', 'weekly')", name="ck_group_schedules_type"),
        sa.CheckConstraint(
            "weekday IS NULL OR weekday BETWEEN 0 AND 6", name="ck_group_schedules_weekday"
        ),
        sa.UniqueConstraint("group_id", "schedule_type", name="uq_group_schedules_group_type"),
    )
    op.create_index("ix_group_schedules_due", "group_schedules", ["enabled", "next_run_at"])
    op.create_table(
        "notification_jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "group_id",
            sa.BigInteger(),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("business_key", sa.String(255), nullable=False),
        sa.Column("notification_type", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by", sa.String(128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("business_key", name="uq_notification_jobs_business_key"),
    )
    op.create_index("ix_notification_jobs_claim", "notification_jobs", ["status", "available_at"])
    op.create_table(
        "delivery_attempts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "job_id",
            sa.BigInteger(),
            sa.ForeignKey("notification_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="started"),
        sa.Column("platform_message_id", sa.String(192), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("job_id", "attempt_no", name="uq_delivery_attempts_job_attempt"),
    )
