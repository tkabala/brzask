"""add article_contents

Revision ID: 60a7527291ee
Revises: 4ad7f5951e79
Create Date: 2026-11-17 11:25:31.864749
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "60a7527291ee"
down_revision: str | None = "4ad7f5951e79"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "article_contents",
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, comment="The full text or transcript."),
        sa.Column(
            "kind",
            sa.Enum("page", "transcript", "description", name="content_kind", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "extracted_by", sa.Text(), nullable=True, comment="Extractor that produced the text."
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('page', 'transcript', 'description')",
            name=op.f("ck_article_contents_content_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_article_contents_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("article_id", name=op.f("pk_article_contents")),
    )


def downgrade() -> None:
    op.drop_table("article_contents")
