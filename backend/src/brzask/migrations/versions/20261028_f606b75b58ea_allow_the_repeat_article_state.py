"""allow the repeat article state

Revision ID: f606b75b58ea
Revises: 91bf7f43d22e
Create Date: 2026-10-28 13:31:51.636319
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f606b75b58ea"
down_revision: str | None = "91bf7f43d22e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate does not compare CHECK constraints; the state's values live in one.
    op.drop_constraint(op.f("ck_articles_article_state"), "articles", type_="check")
    op.create_check_constraint(
        op.f("ck_articles_article_state"), "articles", "state IN ('seen', 'shown', 'repeat')"
    )


def downgrade() -> None:
    # A repeat goes back to being an ordinary unshown article.
    op.execute("UPDATE articles SET state = 'seen' WHERE state = 'repeat'")
    op.drop_constraint(op.f("ck_articles_article_state"), "articles", type_="check")
    op.create_check_constraint(
        op.f("ck_articles_article_state"), "articles", "state IN ('seen', 'shown')"
    )
