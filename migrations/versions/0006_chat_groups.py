"""Chat groups and AstrBot unified_msg_origin (Task 7).

Replaces the legacy `groups` table with a platform-explicit model:

* chat_groups - one row per (platform, external_group_id) with the
  latest unified_msg_origin, group timezone, enable flag and refresh
  timestamp.
* group_memberships - per-user state (display name, last_seen_at,
  role). Private (1:1) chat does not insert here so it cannot be
  notified.

Downgrade drops the new tables only; legacy v0.1 groups / group_members
remain untouched until Task 10 / 27.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_chat_groups"
down_revision: str | None = "0005_multisource_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


GROUP_ROLE_VALUES = "('member', 'admin', 'owner')"
PLATFORM_VALUES = "('qq')"


def upgrade() -> None:
    op.create_table(
        "chat_groups",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("external_group_id", sa.String(64), nullable=False),
        sa.Column("unified_msg_origin", sa.String(256), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Shanghai"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("umo_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "platform",
            "external_group_id",
            name="uq_chat_groups_platform_external",
        ),
        sa.CheckConstraint(
            f"platform IN {PLATFORM_VALUES}",
            name="ck_chat_groups_platform",
        ),
    )
    op.create_index("ix_chat_groups_platform", "chat_groups", ["platform"])

    op.create_table(
        "group_memberships",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "chat_group_id",
            postgresql.UUID(),
            sa.ForeignKey("chat_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_user_id", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "chat_group_id",
            "external_user_id",
            name="uq_group_memberships_group_user",
        ),
        sa.CheckConstraint(
            f"role IN {GROUP_ROLE_VALUES}",
            name="ck_group_memberships_role",
        ),
    )
    op.create_index(
        "ix_group_memberships_chat_group",
        "group_memberships",
        ["chat_group_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_group_memberships_chat_group", table_name="group_memberships")
    op.drop_table("group_memberships")
    op.drop_index("ix_chat_groups_platform", table_name="chat_groups")
    op.drop_table("chat_groups")
