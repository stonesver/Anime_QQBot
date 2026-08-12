"""Add persisted AnimeSchedule controls and operator job support."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_animeschedule_integration"
down_revision: str | None = "0016_content_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "anilist_mapping_policies",
        sa.Column("animeschedule_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "anilist_mapping_policies",
        sa.Column("animeschedule_query_budget", sa.Integer(), nullable=False, server_default="12"),
    )
    op.add_column(
        "anilist_mapping_policies",
        sa.Column(
            "animeschedule_priority_window_days",
            sa.Integer(),
            nullable=False,
            server_default="7",
        ),
    )
    op.add_column(
        "anilist_mapping_policies",
        sa.Column(
            "animeschedule_empty_cooldown_hours",
            sa.Integer(),
            nullable=False,
            server_default="168",
        ),
    )
    op.add_column(
        "anilist_mapping_policies",
        sa.Column(
            "animeschedule_error_cooldown_hours",
            sa.Integer(),
            nullable=False,
            server_default="168",
        ),
    )
    op.create_check_constraint(
        "ck_anilist_policy_animeschedule_budget",
        "anilist_mapping_policies",
        "animeschedule_query_budget BETWEEN 1 AND 30",
    )
    op.create_check_constraint(
        "ck_anilist_policy_animeschedule_window",
        "anilist_mapping_policies",
        "animeschedule_priority_window_days BETWEEN 1 AND 14",
    )
    op.create_check_constraint(
        "ck_anilist_policy_animeschedule_empty_cooldown",
        "anilist_mapping_policies",
        "animeschedule_empty_cooldown_hours BETWEEN 1 AND 720",
    )
    op.create_check_constraint(
        "ck_anilist_policy_animeschedule_error_cooldown",
        "anilist_mapping_policies",
        "animeschedule_error_cooldown_hours BETWEEN 1 AND 720",
    )
    op.drop_constraint("ck_operator_jobs_type", "operator_jobs", type_="check")
    op.create_check_constraint(
        "ck_operator_jobs_type",
        "operator_jobs",
        "job_type IN ('sync_catalog', 'sync_anilist_mapping', 'sync_animeschedule', "
        "'poll_mikan', 'rebuild_projection', 'retry_delivery', 'cleanup_sessions')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_operator_jobs_type", "operator_jobs", type_="check")
    op.create_check_constraint(
        "ck_operator_jobs_type",
        "operator_jobs",
        "job_type IN ('sync_catalog', 'poll_mikan', 'rebuild_projection', "
        "'retry_delivery', 'cleanup_sessions')",
    )
    for name in (
        "ck_anilist_policy_animeschedule_error_cooldown",
        "ck_anilist_policy_animeschedule_empty_cooldown",
        "ck_anilist_policy_animeschedule_window",
        "ck_anilist_policy_animeschedule_budget",
    ):
        op.drop_constraint(name, "anilist_mapping_policies", type_="check")
    for name in (
        "animeschedule_error_cooldown_hours",
        "animeschedule_empty_cooldown_hours",
        "animeschedule_priority_window_days",
        "animeschedule_query_budget",
        "animeschedule_enabled",
    ):
        op.drop_column("anilist_mapping_policies", name)
