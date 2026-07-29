"""Add persisted runtime component status and transition history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_runtime_component_status"
down_revision: str | None = "0012_interaction_delivery_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_CHECK = "status IN ('unknown', 'online', 'qq_offline', 'unreachable')"


def upgrade() -> None:
    op.create_table(
        "runtime_component_states",
        sa.Column("component_name", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("offline_since", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_STATUS_CHECK, name="ck_runtime_component_states_status"),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_runtime_component_states_failures",
        ),
    )
    op.create_table(
        "runtime_component_events",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "component_name",
            sa.String(64),
            sa.ForeignKey(
                "runtime_component_states.component_name",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("previous_status", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("summary", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "previous_status IS NULL OR "
            "previous_status IN ('unknown', 'online', 'qq_offline', 'unreachable')",
            name="ck_runtime_component_events_previous_status",
        ),
        sa.CheckConstraint(_STATUS_CHECK, name="ck_runtime_component_events_status"),
    )
    op.create_index(
        "ix_runtime_component_events_recent",
        "runtime_component_events",
        ["component_name", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runtime_component_events_recent",
        table_name="runtime_component_events",
    )
    op.drop_table("runtime_component_events")
    op.drop_table("runtime_component_states")
