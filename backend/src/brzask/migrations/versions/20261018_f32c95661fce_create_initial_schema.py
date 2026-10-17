"""Create the initial schema.

Revision ID: f32c95661fce
Revises:
Create Date: 2026-10-18 00:52:29.428311
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "f32c95661fce"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Needs a role allowed to create extensions, such as the pgvector image's default user.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "prefix",
            sa.Text(),
            nullable=False,
            comment="First characters of the token, to recognise it.",
        ),
        sa.Column(
            "token_hash",
            sa.Text(),
            nullable=False,
            comment="SHA-256 of the token; tokens are random, so a fast hash is enough.",
        ),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('read', 'write')", name=op.f("ck_api_tokens_token_scope")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("name", name=op.f("uq_api_tokens_name")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_tokens_token_hash")),
    )
    op.create_table(
        "change_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "actor",
            sa.Text(),
            nullable=False,
            comment="e.g. 'user', 'pipeline:review', 'token:<name>'.",
        ),
        sa.Column(
            "action", sa.Text(), nullable=False, comment="e.g. 'source.mute', 'interest.update'."
        ),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the status last changed.",
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'applied', 'rejected', 'reverted')",
            name=op.f("ck_change_log_change_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_change_log")),
    )
    op.create_index(op.f("ix_change_log_created_at"), "change_log", ["created_at"], unique=False)
    op.create_index(
        op.f("ix_change_log_entity_type_entity_id"),
        "change_log",
        ["entity_type", "entity_id"],
        unique=False,
    )
    op.create_table(
        "interests",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column(
            "keywords",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
            comment="Can only widen the topic.",
        ),
        sa.Column(
            "notes",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="Free-text reader notes ('want: ..., skip: ...'); override keywords in prompts.",
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interests")),
        sa.UniqueConstraint("topic", name=op.f("uq_interests_topic")),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False, comment="Also the run_id in logs."),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="running", nullable=False),
        sa.Column("dry_run", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
            comment="Counts and costs reported by the pipeline.",
        ),
        sa.Column(
            "timings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
            comment="Duration of each stage in milliseconds.",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('digest', 'review', 'visited', 'discovery')", name=op.f("ck_runs_run_kind")
        ),
        sa.CheckConstraint(
            "status IN ('running', 'ok', 'skipped', 'failed')", name=op.f("ck_runs_run_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    op.create_index(op.f("ix_runs_kind_started_at"), "runs", ["kind", "started_at"], unique=False)
    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, comment="Feed URL."),
        sa.Column(
            "site_url", sa.Text(), nullable=True, comment="Home page, used to match opened links."
        ),
        sa.Column("kind", sa.String(), server_default="feed", nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column(
            "origin_detail",
            sa.Text(),
            nullable=True,
            comment="Which discovery adapter or interest proposed the source.",
        ),
        sa.Column("note", sa.Text(), nullable=True, comment="Reason for the current status."),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('feed', 'release')", name=op.f("ck_sources_source_kind")),
        sa.CheckConstraint(
            "origin IN ('manual', 'discovery', 'visited', 'opml')",
            name=op.f("ck_sources_source_origin"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'pending', 'rejected', 'muted', 'dead')",
            name=op.f("ck_sources_source_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint("name", name=op.f("uq_sources_name")),
        sa.UniqueConstraint("url", name=op.f("uq_sources_url")),
    )
    op.create_index(op.f("ix_sources_status"), "sources", ["status"], unique=False)
    op.create_table(
        "articles",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("link", sa.Text(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "snippet", sa.Text(), nullable=True, comment="Summary or content from the feed entry."
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("state", sa.String(), server_default="seen", nullable=False),
        sa.Column(
            "rank",
            sa.Integer(),
            nullable=True,
            comment="Position in the LLM ranking; set only for the top candidates.",
        ),
        sa.Column("shown_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="First open; the preference signal.",
        ),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column(
            "extracted_by", sa.Text(), nullable=True, comment="Extractor that produced the text."
        ),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column(
            "embedding_model",
            sa.Text(),
            nullable=True,
            comment="Only vectors of the same model are compared.",
        ),
        sa.Column("digest_date", sa.Date(), nullable=True),
        sa.Column("digest_position", sa.Integer(), nullable=True),
        sa.Column(
            "digest_title", sa.Text(), nullable=True, comment="Title in the digest language."
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("why_it_matters", sa.Text(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state = 'shown' OR digest_date IS NULL",
            name=op.f("ck_articles_only_shown_articles_in_digest"),
        ),
        sa.CheckConstraint("state IN ('seen', 'shown')", name=op.f("ck_articles_article_state")),
        sa.CheckConstraint(
            "(digest_date IS NULL) = (digest_position IS NULL)",
            name=op.f("ck_articles_digest_date_and_position"),
        ),
        sa.CheckConstraint(
            "(embedding IS NULL) = (embedding_model IS NULL)",
            name=op.f("ck_articles_embedding_has_model"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_articles_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_articles")),
        sa.UniqueConstraint(
            "digest_date", "digest_position", name=op.f("uq_articles_digest_date_digest_position")
        ),
        sa.UniqueConstraint("link", name=op.f("uq_articles_link")),
    )
    op.create_index(op.f("ix_articles_first_seen_at"), "articles", ["first_seen_at"], unique=False)
    op.create_index(
        op.f("ix_articles_opened_at"),
        "articles",
        ["opened_at"],
        unique=False,
        postgresql_where=sa.text("opened_at IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_articles_shown_at"),
        "articles",
        ["shown_at"],
        unique=False,
        postgresql_where=sa.text("shown_at IS NOT NULL"),
    )
    op.create_index(op.f("ix_articles_source_id"), "articles", ["source_id"], unique=False)


def downgrade() -> None:
    # The vector extension is left installed; other objects in the database may use it.
    op.drop_index(op.f("ix_articles_source_id"), table_name="articles")
    op.drop_index(
        op.f("ix_articles_shown_at"),
        table_name="articles",
        postgresql_where=sa.text("shown_at IS NOT NULL"),
    )
    op.drop_index(
        op.f("ix_articles_opened_at"),
        table_name="articles",
        postgresql_where=sa.text("opened_at IS NOT NULL"),
    )
    op.drop_index(op.f("ix_articles_first_seen_at"), table_name="articles")
    op.drop_table("articles")
    op.drop_index(op.f("ix_sources_status"), table_name="sources")
    op.drop_table("sources")
    op.drop_table("settings")
    op.drop_index(op.f("ix_runs_kind_started_at"), table_name="runs")
    op.drop_table("runs")
    op.drop_table("interests")
    op.drop_index(op.f("ix_change_log_entity_type_entity_id"), table_name="change_log")
    op.drop_index(op.f("ix_change_log_created_at"), table_name="change_log")
    op.drop_table("change_log")
    op.drop_table("api_tokens")
