"""Create persistent schedules, jobs and delivery attempts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_schedules_and_notifications"
down_revision: str | None = "0003_subscriptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_table("delivery_attempts")
    op.drop_index("ix_notification_jobs_claim", table_name="notification_jobs")
    op.drop_table("notification_jobs")
    op.drop_index("ix_group_schedules_due", table_name="group_schedules")
    op.drop_table("group_schedules")
