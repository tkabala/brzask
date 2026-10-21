"""Database tables. See docs/data-model.md for the states and why they exist."""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from brzask.db.base import Base, TimestampMixin, text_enum

# Width of stored embeddings. Every embedding model is asked for vectors of this
# size (truncated and re-normalised where needed), so the column type never changes.
EMBEDDING_DIMENSIONS = 768


def _id() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(), primary_key=True)


# --- Sources ---------------------------------------------------------------------


class SourceStatus(StrEnum):
    ACTIVE = "active"  # fetched every day
    PENDING = "pending"  # proposed, waiting for a decision
    REJECTED = "rejected"  # declined; kept so it is not proposed again
    MUTED = "muted"  # switched off, by hand or by the source review
    DEAD = "dead"  # the feed no longer works


class SourceKind(StrEnum):
    FEED = "feed"
    RELEASE = "release"  # release notes, judged on content rather than dropped as noise


class SourceOrigin(StrEnum):
    MANUAL = "manual"
    DISCOVERY = "discovery"  # web search and the discovery judge
    VISITED = "visited"  # a domain reached through an opened link
    OPML = "opml"


class Source(TimestampMixin, Base):
    __tablename__ = "sources"

    id: Mapped[int] = _id()
    name: Mapped[str] = mapped_column(comment="Unique ignoring case, as people type names.")
    url: Mapped[str] = mapped_column(unique=True, comment="Feed URL.")
    site_url: Mapped[str | None] = mapped_column(comment="Home page, used to match opened links.")
    kind: Mapped[SourceKind] = mapped_column(
        text_enum(SourceKind, "source_kind"),
        default=SourceKind.FEED,
        server_default=SourceKind.FEED.value,
    )
    status: Mapped[SourceStatus] = mapped_column(text_enum(SourceStatus, "source_status"))
    origin: Mapped[SourceOrigin] = mapped_column(text_enum(SourceOrigin, "source_origin"))
    origin_detail: Mapped[str | None] = mapped_column(
        comment="Which discovery adapter or interest proposed the source."
    )
    note: Mapped[str | None] = mapped_column(comment="Reason for the current status.")
    etag: Mapped[str | None] = mapped_column(comment="ETag of the last fetch, for conditional GET.")
    last_modified: Mapped[str | None] = mapped_column(
        comment="Last-Modified of the last fetch, for conditional GET."
    )

    # Fetch health, updated by every digest run; the source review marks a source
    # dead from it.
    fetched_at: Mapped[datetime | None] = mapped_column(
        comment="Last successful fetch, including 'not modified'."
    )
    failing_since: Mapped[datetime | None] = mapped_column(
        comment="First failed fetch of the current run of failures; null while fetches succeed."
    )
    permanent_failing_since: Mapped[datetime | None] = mapped_column(
        comment="First fetch of the current run of permanent errors (404, 410, 403, not a feed);"
        " null when the last error was temporary."
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        comment="Last failed fetch; null while fetches succeed."
    )
    fetch_failures: Mapped[int] = mapped_column(
        default=0, server_default=text("0"), comment="Failed fetches in a row."
    )
    fetch_error: Mapped[str | None] = mapped_column(
        comment="Error of the last failed fetch; null while fetches succeed."
    )

    articles: Mapped[list["Article"]] = relationship(back_populates="source")

    __table_args__ = (
        Index(None, "status"),
        Index("uq_sources_lower_name", func.lower(name), unique=True),
    )


# --- Interests -------------------------------------------------------------------


class Interest(TimestampMixin, Base):
    __tablename__ = "interests"

    id: Mapped[int] = _id()
    topic: Mapped[str] = mapped_column(comment="Unique ignoring case, as people type topics.")
    keywords: Mapped[list[str]] = mapped_column(
        server_default=text("'{}'"), comment="Can only widen the topic."
    )
    notes: Mapped[str] = mapped_column(
        server_default="",
        comment="Free-text reader notes ('want: ..., skip: ...'); override keywords in prompts.",
    )
    active: Mapped[bool] = mapped_column(server_default=text("true"))

    __table_args__ = (Index("uq_interests_lower_topic", func.lower(topic), unique=True),)


# --- Articles --------------------------------------------------------------------


class ArticleState(StrEnum):
    SEEN = "seen"  # fetched; may be carried over to later days
    SHOWN = "shown"  # picked for a digest


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = _id()
    link: Mapped[str] = mapped_column(unique=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str]
    snippet: Mapped[str | None] = mapped_column(comment="Summary or content from the feed entry.")
    published_at: Mapped[datetime | None]
    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)

    state: Mapped[ArticleState] = mapped_column(
        text_enum(ArticleState, "article_state"),
        default=ArticleState.SEEN,
        server_default=ArticleState.SEEN.value,
    )
    rank: Mapped[int | None] = mapped_column(
        comment="Position in the LLM ranking; set only for the top candidates."
    )
    shown_at: Mapped[datetime | None]
    opened_at: Mapped[datetime | None] = mapped_column(comment="First open; the preference signal.")

    extracted_text: Mapped[str | None] = mapped_column(
        comment="The text that was embedded, so another model can embed it again."
    )
    extracted_by: Mapped[str | None] = mapped_column(comment="Extractor that produced the text.")

    # Set when the article is picked for a digest.
    digest_date: Mapped[date | None]
    digest_position: Mapped[int | None]
    digest_title: Mapped[str | None] = mapped_column(comment="Title in the digest language.")
    summary: Mapped[str | None]
    why_it_matters: Mapped[str | None]
    topic: Mapped[str | None]

    source: Mapped[Source | None] = relationship(back_populates="articles")

    __table_args__ = (
        CheckConstraint(
            "(digest_date IS NULL) = (digest_position IS NULL)", name="digest_date_and_position"
        ),
        CheckConstraint(
            "state = 'shown' OR digest_date IS NULL", name="only_shown_articles_in_digest"
        ),
        UniqueConstraint("digest_date", "digest_position"),
        Index(None, "opened_at", postgresql_where=text("opened_at IS NOT NULL")),
        Index(None, "shown_at", postgresql_where=text("shown_at IS NOT NULL")),
    )


class ArticleEmbedding(Base):
    """An article's vector from one model; an article has one per model that embedded it."""

    __tablename__ = "article_embeddings"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    model: Mapped[str] = mapped_column(
        primary_key=True, comment="Only vectors of the same model are compared."
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index(None, "model", "article_id"),)


# --- Runs ------------------------------------------------------------------------


class RunKind(StrEnum):
    DIGEST = "digest"
    REVIEW = "review"
    VISITED = "visited"
    DISCOVERY = "discovery"


class RunStatus(StrEnum):
    RUNNING = "running"
    OK = "ok"
    SKIPPED = "skipped"  # nothing to do: paused, or today's digest already exists
    FAILED = "failed"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, comment="Also the run_id in logs.")
    kind: Mapped[RunKind] = mapped_column(text_enum(RunKind, "run_kind"))
    status: Mapped[RunStatus] = mapped_column(
        text_enum(RunStatus, "run_status"),
        default=RunStatus.RUNNING,
        server_default=RunStatus.RUNNING.value,
    )
    dry_run: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    stats: Mapped[dict[str, Any]] = mapped_column(
        server_default=text("'{}'"), comment="Counts and costs reported by the pipeline."
    )
    timings: Mapped[dict[str, Any]] = mapped_column(
        server_default=text("'{}'"), comment="Duration of each stage in milliseconds."
    )
    error: Mapped[str | None]

    __table_args__ = (Index(None, "kind", "started_at"),)


# --- Settings stored in the database ----------------------------------------------


class Setting(Base):
    """Values changed at runtime (e.g. a pause), as opposed to environment settings."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[dict[str, Any]]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


# --- Change log ------------------------------------------------------------------


class ChangeStatus(StrEnum):
    PROPOSED = "proposed"  # waiting for approval
    APPLIED = "applied"
    REJECTED = "rejected"
    REVERTED = "reverted"


class Change(Base):
    """A change to sources, interests or configuration, by a person, a pipeline or an agent."""

    __tablename__ = "change_log"

    id: Mapped[int] = _id()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    actor: Mapped[str] = mapped_column(comment="e.g. 'user', 'pipeline:review', 'token:<name>'.")
    action: Mapped[str] = mapped_column(comment="e.g. 'source.mute', 'interest.update'.")
    entity_type: Mapped[str]
    entity_id: Mapped[str | None]
    before: Mapped[dict[str, Any] | None]
    after: Mapped[dict[str, Any] | None]
    reason: Mapped[str | None]
    status: Mapped[ChangeStatus] = mapped_column(text_enum(ChangeStatus, "change_status"))
    decided_at: Mapped[datetime | None] = mapped_column(comment="When the status last changed.")

    __table_args__ = (Index(None, "entity_type", "entity_id"),)


# --- API tokens ------------------------------------------------------------------


class TokenScope(StrEnum):
    READ = "read"
    WRITE = "write"


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = _id()
    name: Mapped[str] = mapped_column(unique=True)
    prefix: Mapped[str] = mapped_column(comment="First characters of the token, to recognise it.")
    token_hash: Mapped[str] = mapped_column(
        unique=True,
        comment="SHA-256 of the token; tokens are random, so a fast hash is enough.",
    )
    scope: Mapped[TokenScope] = mapped_column(text_enum(TokenScope, "token_scope"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


# --- Login sessions --------------------------------------------------------------


class LoginSession(Base):
    """A browser logged in with the password; logging out deletes it."""

    __tablename__ = "login_sessions"

    id: Mapped[int] = _id()
    token_hash: Mapped[str] = mapped_column(
        unique=True,
        comment="SHA-256 of the cookie value; tokens are random, so a fast hash is enough.",
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(index=True)
    last_used_at: Mapped[datetime | None]
