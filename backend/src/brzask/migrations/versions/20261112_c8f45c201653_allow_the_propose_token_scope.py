"""allow the propose token scope

Revision ID: c8f45c201653
Revises: 10e4ee0bbd3f
Create Date: 2026-11-12 09:21:20.178816
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c8f45c201653"
down_revision: str | None = "10e4ee0bbd3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate does not compare CHECK constraints; the scope's values live in one.
    op.drop_constraint(op.f("ck_api_tokens_token_scope"), "api_tokens", type_="check")
    op.create_check_constraint(
        op.f("ck_api_tokens_token_scope"),
        "api_tokens",
        "scope IN ('read', 'write', 'propose', 'feed')",
    )


def downgrade() -> None:
    # A propose token cannot exist before this revision.
    op.execute("DELETE FROM api_tokens WHERE scope = 'propose'")
    op.drop_constraint(op.f("ck_api_tokens_token_scope"), "api_tokens", type_="check")
    op.create_check_constraint(
        op.f("ck_api_tokens_token_scope"), "api_tokens", "scope IN ('read', 'write', 'feed')"
    )
