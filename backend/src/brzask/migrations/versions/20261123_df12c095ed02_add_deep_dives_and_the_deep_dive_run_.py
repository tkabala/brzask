"""add deep_dives and the deep_dive run kind

Revision ID: df12c095ed02
Revises: e852c772fa89
Create Date: 2026-11-23 08:05:52.000377
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "df12c095ed02"
down_revision: str | None = "e852c772fa89"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate does not compare CHECK constraints; the run kind's values live in one.
    op.drop_constraint(op.f("ck_runs_run_kind"), "runs", type_="check")
    op.create_check_constraint(
        op.f("ck_runs_run_kind"),
        "runs",
        "kind IN ('digest', 'review', 'visited', 'discovery', 'replay', 'deep_dive')",
    )
    op.create_table(
        "deep_dives",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "focus",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
            comment="The reader's focus line; empty when none.",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued", "running", "done", "failed", name="deep_dive_status", native_enum=False
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "report",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="{background, practice, further}; sources cited by number.",
        ),
        sa.Column(
            "sources",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
            comment="Gathered sources: [{n, url, title, origin, article_id}].",
        ),
        sa.Column(
            "thin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Written from the article alone.",
        ),
        sa.Column(
            "searched_web",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="A web search answered.",
        ),
        sa.Column("model", sa.Text(), nullable=True, comment="The LLM that wrote the report."),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name=op.f("ck_deep_dives_deep_dive_status"),
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_deep_dives_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_deep_dives_run_id_runs"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deep_dives")),
    )
    op.create_index(op.f("ix_deep_dives_article_id"), "deep_dives", ["article_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_deep_dives_article_id"), table_name="deep_dives")
    op.drop_table("deep_dives")
    # A deep dive run cannot exist before this revision.
    op.execute("DELETE FROM runs WHERE kind = 'deep_dive'")
    op.drop_constraint(op.f("ck_runs_run_kind"), "runs", type_="check")
    op.create_check_constraint(
        op.f("ck_runs_run_kind"),
        "runs",
        "kind IN ('digest', 'review', 'visited', 'discovery', 'replay')",
    )
