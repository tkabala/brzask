"""record which agent started a run

Revision ID: 4ad7f5951e79
Revises: a3623d7085f6
Create Date: 2026-11-13 12:51:54.699101
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4ad7f5951e79"
down_revision: str | None = "a3623d7085f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "started_by",
            sa.Text(),
            nullable=True,
            comment="agent:<token name> for a run started over MCP; "
            "empty for the scheduler and the CLI.",
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "started_by")
