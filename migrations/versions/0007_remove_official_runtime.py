"""Remove official QQ bot runtime tables (Task 10).

Drops legacy v0.1 tables that were tied to QQ official bot identity
(group_openid, member_openid, admin identities by openid, and old
delivery/notification/schedule tables). The new chat_groups /
group_memberships tables (0006) are NOT affected.

Downgrade recreates the old table structure but does not restore
data that was explicitly discarded.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_remove_official_runtime"
down_revision: str | None = "0006_chat_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    # Restore empty table structures; data is not recovered.
    op.create_table(
        "groups",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("group_openid", sa.String(128), nullable=False, unique=True),
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
    )
    op.create_table(
        "group_members",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
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
        sa.UniqueConstraint("group_id", "member_openid"),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member')"),
    )
    op.create_table(
        "admin_identities",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("group_openid", sa.String(128), nullable=False),
        sa.Column("member_openid", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("group_openid", "member_openid"),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("group_openid", sa.String(128), nullable=False),
        sa.Column("member_openid", sa.String(128), nullable=False),
        sa.Column(
            "subject_id",
            sa.BigInteger(),
            sa.ForeignKey("anime_subjects.subject_id"),
            nullable=False,
        ),
        sa.Column("notify_airing", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notify_resource", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("group_openid", "member_openid", "subject_id"),
    )
    op.create_table(
        "processed_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("platform_event_id", sa.String(192), nullable=False, unique=True),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(64), primary_key=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "group_schedules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("group_openid", sa.String(128), nullable=False),
        sa.Column("schedule_kind", sa.String(32), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.UniqueConstraint("group_openid", "schedule_kind"),
    )
    op.create_table(
        "notification_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("group_openid", sa.String(128), nullable=False),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("business_key", sa.String(256), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("group_openid", "job_type", "business_key"),
    )
    op.create_table(
        "delivery_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.BigInteger(), sa.ForeignKey("notification_jobs.id"), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("response_summary", sa.Text(), nullable=True),
        sa.Column(
            "attempted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
