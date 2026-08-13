"""Add configurable LLM routing policy fields.

revision: 0019_configurable_mentions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_configurable_mentions"
down_revision: str | None = "0018_minimax_readonly_tools"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "group_runtime_settings",
        sa.Column(
            "llm_mode",
            sa.String(length=16),
            nullable=False,
            server_default="anime_only",
        ),
    )
    op.execute(
        "UPDATE group_runtime_settings SET llm_mode = 'general' WHERE general_chat_enabled IS TRUE"
    )
    op.add_column(
        "group_runtime_settings",
        sa.Column(
            "llm_image_reply_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_check_constraint(
        "ck_group_runtime_settings_llm_mode",
        "group_runtime_settings",
        "llm_mode IN ('disabled', 'anime_only', 'general')",
    )
    op.drop_column("group_runtime_settings", "general_chat_enabled")
    op.create_table(
        "mention_command_policies",
        sa.Column("key", sa.String(length=32), primary_key=True),
        sa.Column("aliases", postgresql.JSONB(), nullable=False),
        sa.Column("customized", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(aliases) = 'object'",
            name="ck_mention_command_policies_aliases_object",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_mention_command_policies_version",
        ),
    )


def downgrade() -> None:
    op.drop_table("mention_command_policies")
    op.add_column(
        "group_runtime_settings",
        sa.Column(
            "general_chat_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        "UPDATE group_runtime_settings SET general_chat_enabled = TRUE WHERE llm_mode = 'general'"
    )
    op.drop_constraint(
        "ck_group_runtime_settings_llm_mode",
        "group_runtime_settings",
        type_="check",
    )
    op.drop_column("group_runtime_settings", "llm_image_reply_enabled")
    op.drop_column("group_runtime_settings", "llm_mode")
