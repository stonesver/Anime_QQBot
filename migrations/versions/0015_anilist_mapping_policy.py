"""Persist operator-controlled AniList mapping discovery guardrails."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_anilist_mapping_policy"
down_revision: str | None = "0014_anilist_mapping_assessments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "anilist_mapping_policies",
        sa.Column("key", sa.String(32), primary_key=True),
        sa.Column("query_budget", sa.Integer(), nullable=False),
        sa.Column("priority_window_days", sa.Integer(), nullable=False),
        sa.Column("retry_cooldown_hours", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "query_budget >= 1 AND query_budget <= 30", name="ck_anilist_policy_budget"
        ),
        sa.CheckConstraint(
            "priority_window_days >= 1 AND priority_window_days <= 14",
            name="ck_anilist_policy_window",
        ),
        sa.CheckConstraint(
            "retry_cooldown_hours >= 1 AND retry_cooldown_hours <= 168",
            name="ck_anilist_policy_cooldown",
        ),
    )


def downgrade() -> None:
    op.drop_table("anilist_mapping_policies")
