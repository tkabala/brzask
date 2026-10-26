"""name manual source rejections source.reject

Revision ID: 91bf7f43d22e
Revises: 01745d57d6ab
Create Date: 2026-10-26 14:51:44.773719
"""

from collections.abc import Sequence

from alembic import op

revision: str = "91bf7f43d22e"
down_revision: str | None = "01745d57d6ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rejections by hand were recorded as source.rejected, discovery's as
    # source.reject; one name lets a filter by action find both.
    op.execute("UPDATE change_log SET action = 'source.reject' WHERE action = 'source.rejected'")


def downgrade() -> None:
    # The renamed rows cannot be told apart from discovery's any more; the
    # single name is valid for the previous code too.
    pass
