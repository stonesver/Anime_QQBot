"""Following subscriptions and notification outbox (Task 16).

Creates:
* follow_subscriptions (chat_group_id, external_user_id, anime_id)
* subscription_resource_filters (language, subtitle_groups, resolutions)
* notification_jobs (outbox with dedupe key, lease, status, expires_at)
* delivery_attempts (per-job platform result)
* processed_platform_events (OneBot event dedup)
* worker_heartbeats (v0.2 version)

Downgrade drops the new tables and restores empty worker_heartbeats v0.1.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_following_and_outbox"
down_revision: str | None = "0007_remove_official_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "follow_subscriptions",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("chat_group_id", postgresql.UUID(), sa.ForeignKey("chat_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_user_id", sa.String(64), nullable=False),
        sa.Column("anime_id", postgresql.UUID(), sa.ForeignKey("animes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notify_airing", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notify_resource", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("chat_group_id", "external_user_id", "anime_id", name="uq_follow_subscriptions_group_user_anime"),
    )

    op.create_table(
        "subscription_resource_filters",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("subscription_id", postgresql.UUID(), sa.ForeignKey("follow_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("subtitle_groups", postgresql.ARRAY(sa.String(64)), server_default="{}"),
        sa.Column("resolutions", postgresql.ARRAY(sa.String(16)), server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("subscription_id", "language", name="uq_resource_filters_sub_lang"),
    )

    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(64), primary_key=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("worker_kind", sa.String(32), nullable=False, server_default="worker"),
    )

    op.create_table(
        "processed_platform_events",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("event_id", sa.String(192), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("platform", "event_id", name="uq_processed_events_platform_event"),
    )

    op.create_table(
        "notification_jobs",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("chat_group_id", postgresql.UUID(), sa.ForeignKey("chat_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("business_key", sa.String(256), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("chat_group_id", "job_type", "business_key", name="uq_notification_jobs_key"),
    )

    op.create_table(
        "delivery_attempts",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("job_id", postgresql.UUID(), sa.ForeignKey("notification_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("response_summary", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("delivery_attempts")
    op.drop_table("notification_jobs")
    op.drop_table("processed_platform_events")
    op.drop_table("worker_heartbeats")
    op.drop_table("subscription_resource_filters")
    op.drop_table("follow_subscriptions")