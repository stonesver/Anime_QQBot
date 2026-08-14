"""Allow opaque source identifiers longer than 128 characters."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_external_entry_text_ids"
down_revision: str | None = "0019_configurable_mentions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "external_entries",
        "external_id",
        existing_type=sa.String(length=128),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "external_entries",
        "external_id",
        existing_type=sa.Text(),
        type_=sa.String(length=128),
        existing_nullable=False,
    )
