"""add articles.brief_opened_at

Revision ID: e852c772fa89
Revises: 15dcc88b8cce
Create Date: 2026-11-17 14:05:00.657305
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e852c772fa89"
down_revision: str | None = "15dcc88b8cce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "articles",
        sa.Column(
            "brief_opened_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="First view of the brief; a preference signal with opened_at.",
        ),
    )
    op.create_index(
        op.f("ix_articles_brief_opened_at"),
        "articles",
        ["brief_opened_at"],
        unique=False,
        postgresql_where=sa.text("brief_opened_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_articles_brief_opened_at"),
        table_name="articles",
        postgresql_where=sa.text("brief_opened_at IS NOT NULL"),
    )
    op.drop_column("articles", "brief_opened_at")
