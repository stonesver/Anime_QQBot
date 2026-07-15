"""Create group-scoped anime subscriptions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_subscriptions"
down_revision: str | None = "0002_catalog_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index("ix_subscriptions_group_enabled", table_name="subscriptions")
    op.drop_table("subscriptions")
