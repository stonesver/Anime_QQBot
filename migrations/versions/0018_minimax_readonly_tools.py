"""Add the per-group general LLM chat policy."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_minimax_readonly_tools"
down_revision: str | None = "0017_animeschedule_integration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "group_runtime_settings",
        sa.Column(
            "general_chat_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("group_runtime_settings", "general_chat_enabled")
