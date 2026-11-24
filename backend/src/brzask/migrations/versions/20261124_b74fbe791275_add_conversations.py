"""add conversations

Revision ID: b74fbe791275
Revises: df12c095ed02
Create Date: 2026-11-24 14:03:16.943190
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b74fbe791275"
down_revision: str | None = "df12c095ed02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_conversations_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("article_id", name=op.f("uq_conversations_article_id")),
    )
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", name="message_role", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "answer",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="{answer: [{text, sources}], enough, suggestions}; null until written.",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "done", "answering", "searching", "failed", name="message_status", native_enum=False
            ),
            server_default="done",
            nullable=False,
        ),
        sa.Column(
            "searched",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Answered after a search round.",
        ),
        sa.Column(
            "note", sa.Text(), nullable=True, comment="Shown under the answer, e.g. a search's."
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True, comment="The LLM that wrote the answer."),
        sa.Column(
            "usage",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
            comment="Usage of every call made for this answer, shaped as a run's.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("text", sa.Text(), nullable=True, comment="The question; null for answers."),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name=op.f("ck_conversation_messages_message_role")
        ),
        sa.CheckConstraint(
            "status IN ('done', 'answering', 'searching', 'failed')",
            name=op.f("ck_conversation_messages_message_status"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_conversation_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_messages")),
    )
    op.create_index(
        op.f("ix_conversation_messages_conversation_id"),
        "conversation_messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_table(
        "conversation_sources",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False, comment="The number answers cite it by."),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "origin",
            sa.Enum(
                "article",
                "report",
                "archive",
                "web",
                name="conversation_source_origin",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("article_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "text", sa.Text(), nullable=True, comment="Text read for answers; null when none."
        ),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "origin IN ('article', 'report', 'archive', 'web')",
            name=op.f("ck_conversation_sources_conversation_source_origin"),
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_conversation_sources_article_id_articles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_conversation_sources_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_sources")),
        sa.UniqueConstraint(
            "conversation_id", "n", name=op.f("uq_conversation_sources_conversation_id_n")
        ),
        sa.UniqueConstraint(
            "conversation_id", "url", name=op.f("uq_conversation_sources_conversation_id_url")
        ),
    )


def downgrade() -> None:
    op.drop_table("conversation_sources")
    op.drop_index(
        op.f("ix_conversation_messages_conversation_id"), table_name="conversation_messages"
    )
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
