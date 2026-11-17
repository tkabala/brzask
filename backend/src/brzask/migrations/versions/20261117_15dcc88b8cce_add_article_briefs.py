"""add article_briefs

Revision ID: 15dcc88b8cce
Revises: 60a7527291ee
Create Date: 2026-11-17 13:44:57.358018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "15dcc88b8cce"
down_revision: str | None = "60a7527291ee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "article_briefs",
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("gist", sa.Text(), nullable=False),
        sa.Column("points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("caveats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "chapters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Video chapters: [{start: seconds, title}].",
        ),
        sa.Column(
            "basis",
            sa.Enum(
                "full_text",
                "transcript",
                "partial",
                "description",
                name="brief_basis",
                native_enum=False,
            ),
            nullable=False,
            comment="What text the brief was written from.",
        ),
        sa.Column("model", sa.Text(), nullable=False, comment="The LLM that wrote it."),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "basis IN ('full_text', 'transcript', 'partial', 'description')",
            name=op.f("ck_article_briefs_brief_basis"),
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_article_briefs_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("article_id", name=op.f("pk_article_briefs")),
    )


def downgrade() -> None:
    op.drop_table("article_briefs")
