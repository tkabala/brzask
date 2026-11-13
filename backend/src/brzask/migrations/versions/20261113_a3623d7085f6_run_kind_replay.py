"""allow the replay run kind

Revision ID: a3623d7085f6
Revises: c8f45c201653
Create Date: 2026-11-13 10:28:05.883569
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3623d7085f6"
down_revision: str | None = "c8f45c201653"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate does not compare CHECK constraints; the kind's values live in one.
    op.drop_constraint(op.f("ck_runs_run_kind"), "runs", type_="check")
    op.create_check_constraint(
        op.f("ck_runs_run_kind"),
        "runs",
        "kind IN ('digest', 'review', 'visited', 'discovery', 'replay')",
    )


def downgrade() -> None:
    # A replay run cannot exist before this revision.
    op.execute("DELETE FROM runs WHERE kind = 'replay'")
    op.drop_constraint(op.f("ck_runs_run_kind"), "runs", type_="check")
    op.create_check_constraint(
        op.f("ck_runs_run_kind"), "runs", "kind IN ('digest', 'review', 'visited', 'discovery')"
    )
