"""Database tables. See docs/data-model.md for the states and why they exist."""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ColumnElement,
    ForeignKey,
    Identity,
    Index,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
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
    REPEAT = "repeat"  # dropped as a repeat of a shown article; never a candidate again


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
    brief_opened_at: Mapped[datetime | None] = mapped_column(
        comment="First view of the brief; a preference signal with opened_at."
    )

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

    @hybrid_property
    def engaged_at(self) -> datetime | None:
        """When the reader first showed interest: the earlier of opening the original
        and entering the brief (ADR 0025). Every "the reader wanted this" reads this.
        """
        signals = [at for at in (self.opened_at, self.brief_opened_at) if at is not None]
        return min(signals, default=None)

    @engaged_at.inplace.expression
    @classmethod
    def _engaged_at_expression(cls) -> ColumnElement[datetime | None]:
        # Postgres' LEAST ignores nulls: null only when both are.
        return func.least(cls.opened_at, cls.brief_opened_at)

    __table_args__ = (
        CheckConstraint(
            "(digest_date IS NULL) = (digest_position IS NULL)", name="digest_date_and_position"
        ),
        CheckConstraint(
            "state = 'shown' OR digest_date IS NULL", name="only_shown_articles_in_digest"
        ),
        UniqueConstraint("digest_date", "digest_position"),
        Index(None, "opened_at", postgresql_where=text("opened_at IS NOT NULL")),
        Index(None, "brief_opened_at", postgresql_where=text("brief_opened_at IS NOT NULL")),
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


class ContentKind(StrEnum):
    PAGE = "page"  # the extracted article page
    TRANSCRIPT = "transcript"  # a video's captions
    DESCRIPTION = "description"  # only the feed's snippet was usable


class ArticleContent(Base):
    """The untruncated text of a picked article, kept for reading it in full."""

    __tablename__ = "article_contents"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    text: Mapped[str] = mapped_column(comment="The full text or transcript.")
    kind: Mapped[ContentKind] = mapped_column(text_enum(ContentKind, "content_kind"))
    extracted_by: Mapped[str | None] = mapped_column(comment="Extractor that produced the text.")
    fetched_at: Mapped[datetime] = mapped_column(server_default=func.now())


class BriefBasis(StrEnum):
    FULL_TEXT = "full_text"  # the whole extracted page
    TRANSCRIPT = "transcript"  # the whole transcript of a video
    PARTIAL = "partial"  # the beginning of a text too long to brief whole
    DESCRIPTION = "description"  # only the feed's snippet


class ArticleBrief(Base):
    """What a picked article says, written from its stored text after the digest run."""

    __tablename__ = "article_briefs"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    gist: Mapped[str]
    points: Mapped[list[str]] = mapped_column(JSONB)
    caveats: Mapped[list[str]] = mapped_column(JSONB)
    chapters: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, comment="Video chapters: [{start: seconds, title}]."
    )
    basis: Mapped[BriefBasis] = mapped_column(
        text_enum(BriefBasis, "brief_basis"), comment="What text the brief was written from."
    )
    model: Mapped[str] = mapped_column(comment="The LLM that wrote it.")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DeepDiveStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class DeepDive(Base):
    """A report on one article, written on the reader's request from gathered sources."""

    __tablename__ = "deep_dives"

    id: Mapped[int] = _id()
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    focus: Mapped[str] = mapped_column(
        server_default=text("''"), comment="The reader's focus line; empty when none."
    )
    status: Mapped[DeepDiveStatus] = mapped_column(
        text_enum(DeepDiveStatus, "deep_dive_status"),
        default=DeepDiveStatus.QUEUED,
        server_default=DeepDiveStatus.QUEUED.value,
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    report: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="{background, practice, further}; sources cited by number."
    )
    sources: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        server_default=text("'[]'"),
        default=list,
        comment="Gathered sources: [{n, url, title, origin, article_id}].",
    )
    thin: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"), comment="Written from the article alone."
    )
    searched_web: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"), comment="A web search answered."
    )
    model: Mapped[str | None] = mapped_column(comment="The LLM that wrote the report.")
    error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    read_at: Mapped[datetime | None]

    article: Mapped[Article] = relationship(lazy="joined")


class Conversation(Base):
    """The reader's questions about one article and their answers."""

    __tablename__ = "conversations"

    id: Mapped[int] = _id()
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    article: Mapped[Article] = relationship(lazy="joined")


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(StrEnum):
    DONE = "done"
    ANSWERING = "answering"  # the model is writing the answer
    SEARCHING = "searching"  # a search round runs, then the answer is written again
    FAILED = "failed"


class ConversationMessage(Base):
    """A question (user) or its answer (assistant); questions are always done."""

    __tablename__ = "conversation_messages"

    id: Mapped[int] = _id()
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(text_enum(MessageRole, "message_role"))
    answer: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="{answer: [{text, sources}], enough, suggestions}; null until written."
    )
    status: Mapped[MessageStatus] = mapped_column(
        text_enum(MessageStatus, "message_status"),
        default=MessageStatus.DONE,
        server_default=MessageStatus.DONE.value,
    )
    searched: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"), comment="Answered after a search round."
    )
    note: Mapped[str | None] = mapped_column(comment="Shown under the answer, e.g. a search's.")
    error: Mapped[str | None]
    model: Mapped[str | None] = mapped_column(comment="The LLM that wrote the answer.")
    usage: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=text("'{}'"),
        default=dict,
        comment="Usage of every call made for this answer, shaped as a run's.",
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    # Last: in the class body the name hides sqlalchemy's text() used above.
    text: Mapped[str | None] = mapped_column(comment="The question; null for answers.")

    conversation: Mapped[Conversation] = relationship(lazy="joined")


class ConversationSourceOrigin(StrEnum):
    ARTICLE = "article"  # the article itself, always number 1
    REPORT = "report"  # a web source of one of the article's deep dives
    ARCHIVE = "archive"  # a stored article
    WEB = "web"  # found by a search round


class ConversationSource(Base):
    """Material an answer may cite, numbered for the conversation's whole life."""

    __tablename__ = "conversation_sources"
    __table_args__ = (
        UniqueConstraint("conversation_id", "n"),
        UniqueConstraint("conversation_id", "url"),
    )

    id: Mapped[int] = _id()
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    n: Mapped[int] = mapped_column(comment="The number answers cite it by.")
    url: Mapped[str]
    title: Mapped[str]
    origin: Mapped[ConversationSourceOrigin] = mapped_column(
        text_enum(ConversationSourceOrigin, "conversation_source_origin")
    )
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"))
    text: Mapped[str | None] = mapped_column(comment="Text read for answers; null when none.")
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())


# --- Runs ------------------------------------------------------------------------


class RunKind(StrEnum):
    DIGEST = "digest"
    REVIEW = "review"
    VISITED = "visited"
    DISCOVERY = "discovery"
    # A replay an agent started: recorded, so its cost counts towards the
    # spending limits, but not a pipeline (nothing schedules or forces it).
    REPLAY = "replay"
    # A deep dive the reader asked for: recorded for its cost, run by the api.
    DEEP_DIVE = "deep_dive"


# The kinds the worker schedules, in the order of pipelines sharing a time.
PIPELINE_KINDS = (RunKind.DIGEST, RunKind.REVIEW, RunKind.VISITED, RunKind.DISCOVERY)


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
    started_by: Mapped[str | None] = mapped_column(
        comment="agent:<token name> for a run started over MCP; "
        "empty for the scheduler and the CLI."
    )

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
    PROPOSE = "propose"  # changes wait for the owner's approval
    FEED = "feed"  # only the digest feed, carried in its URL


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
