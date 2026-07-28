"""Add v0.3 interaction, delivery and owner-operation controls."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_interaction_delivery_admin"
down_revision: str | None = "0011_complete_mikan_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "group_runtime_settings",
        sa.Column(
            "chat_group_id",
            postgresql.UUID(),
            sa.ForeignKey("chat_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("mention_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "direct_shortcuts_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "active_notifications_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("quiet_start_minute", sa.Integer(), nullable=True),
        sa.Column("quiet_end_minute", sa.Integer(), nullable=True),
        sa.Column("group_interval_seconds", sa.Float(), nullable=True),
        sa.Column("proactive_interval_seconds", sa.Float(), nullable=True),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pause_reason", sa.String(256), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(quiet_start_minute IS NULL) = (quiet_end_minute IS NULL)",
            name="ck_group_runtime_settings_quiet_pair",
        ),
        sa.CheckConstraint(
            "quiet_start_minute IS NULL OR quiet_start_minute BETWEEN 0 AND 1439",
            name="ck_group_runtime_settings_quiet_start",
        ),
        sa.CheckConstraint(
            "quiet_end_minute IS NULL OR quiet_end_minute BETWEEN 0 AND 1439",
            name="ck_group_runtime_settings_quiet_end",
        ),
        sa.CheckConstraint("version > 0", name="ck_group_runtime_settings_version"),
    )
    op.create_table(
        "interaction_sessions",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("external_group_id", sa.String(64), nullable=False),
        sa.Column("external_user_id", sa.String(64), nullable=False),
        sa.Column("candidates", postgresql.JSONB(), nullable=False),
        sa.Column("result_message_id", sa.String(192), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(candidates) = 'array'",
            name="ck_interaction_sessions_candidates_array",
        ),
        sa.UniqueConstraint(
            "platform",
            "external_group_id",
            "external_user_id",
            name="uq_interaction_sessions_scope",
        ),
    )
    op.create_index("ix_interaction_sessions_expires_at", "interaction_sessions", ["expires_at"])
    op.create_table(
        "delivery_controls",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("scope_kind", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(64), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("circuit_open", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(256), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resumed_by", sa.String(128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_kind IN ('global', 'group')",
            name="ck_delivery_controls_scope_kind",
        ),
        sa.UniqueConstraint("scope_kind", "scope_id", name="uq_delivery_controls_scope"),
    )
    op.create_table(
        "operator_jobs",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(192), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_summary", postgresql.JSONB(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_operator_jobs_status",
        ),
        sa.CheckConstraint(
            "job_type IN ('sync_catalog', 'poll_mikan', 'rebuild_projection', "
            "'retry_delivery', 'cleanup_sessions')",
            name="ck_operator_jobs_type",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_operator_jobs_idempotency"),
    )
    op.create_index(
        "ix_operator_jobs_claim", "operator_jobs", ["status", "available_at", "created_at"]
    )
    op.create_table(
        "admin_audit_events",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(128), nullable=True),
        sa.Column("before_summary", postgresql.JSONB(), nullable=True),
        sa.Column("after_summary", postgresql.JSONB(), nullable=True),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "result IN ('success', 'rejected', 'failed')",
            name="ck_admin_audit_events_result",
        ),
    )
    op.create_index("ix_admin_audit_events_created_at", "admin_audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_audit_events_created_at", table_name="admin_audit_events")
    op.drop_table("admin_audit_events")
    op.drop_index("ix_operator_jobs_claim", table_name="operator_jobs")
    op.drop_table("operator_jobs")
    op.drop_table("delivery_controls")
    op.drop_index("ix_interaction_sessions_expires_at", table_name="interaction_sessions")
    op.drop_table("interaction_sessions")
    op.drop_table("group_runtime_settings")
