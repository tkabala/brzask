"""allow the feed token scope

Revision ID: 10e4ee0bbd3f
Revises: f606b75b58ea
Create Date: 2026-11-04 16:00:05.267825
"""

from collections.abc import Sequence

from alembic import op

revision: str = "10e4ee0bbd3f"
down_revision: str | None = "f606b75b58ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate does not compare CHECK constraints; the scope's values live in one.
    op.drop_constraint(op.f("ck_api_tokens_token_scope"), "api_tokens", type_="check")
    op.create_check_constraint(
        op.f("ck_api_tokens_token_scope"), "api_tokens", "scope IN ('read', 'write', 'feed')"
    )


def downgrade() -> None:
    # A feed token cannot exist before this revision.
    op.execute("DELETE FROM api_tokens WHERE scope = 'feed'")
    op.drop_constraint(op.f("ck_api_tokens_token_scope"), "api_tokens", type_="check")
    op.create_check_constraint(
        op.f("ck_api_tokens_token_scope"), "api_tokens", "scope IN ('read', 'write')"
    )
