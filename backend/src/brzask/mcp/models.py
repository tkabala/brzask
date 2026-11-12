"""What the tools return.

Fields under `external` hold text that third parties wrote, or that a model
wrote while reading it: titles, summaries, article text, source names (most
come from feed titles), run stats and change details (which carry them).
Everything else is written by brzask or the owner.
"""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from brzask.api.sources import SourceActivity, SourceHealth
from brzask.db.models import (
    Article,
    ArticleState,
    Change,
    ChangeStatus,
    Interest,
    Run,
    RunKind,
    RunStatus,
    Source,
    SourceKind,
    SourceOrigin,
    SourceStatus,
)
from brzask.mcp.content import cap
from brzask.repositories.sources import SourceStats
from brzask.services.rollback import describe_change


class ArticleExternal(BaseModel):
    title: str = Field(description="In the digest language when it was in a digest.")
    original_title: str
    summary: str | None
    why_it_matters: str | None = Field(description="The selection's reason, for the reader.")
    source_name: str | None


class ArticleItem(BaseModel):
    id: int
    link: str = Field(description="The article's own URL; opening it records nothing.")
    source_id: int | None
    topic: str | None = Field(description="The interest it was picked for.")
    state: ArticleState
    published_at: datetime | None
    digest_date: date | None
    position: int | None = Field(description="1-based place in its digest.")
    shown_at: datetime | None
    opened_at: datetime | None = Field(description="First open by the owner.")
    external: ArticleExternal

    @classmethod
    def of(cls, article: Article) -> "ArticleItem":
        source = article.source
        return cls(
            id=article.id,
            link=article.link,
            source_id=source.id if source else None,
            topic=article.topic,
            state=article.state,
            published_at=article.published_at,
            digest_date=article.digest_date,
            position=article.digest_position,
            shown_at=article.shown_at,
            opened_at=article.opened_at,
            external=ArticleExternal(
                title=article.digest_title or article.title,
                original_title=article.title,
                summary=article.summary,
                why_it_matters=article.why_it_matters,
                source_name=source.name if source else None,
            ),
        )


class ArticleTextExternal(ArticleExternal):
    text: str | None = Field(description="Stored text of the page or feed entry, cut if long.")
    truncated: bool


class ArticleDetail(ArticleItem):
    extracted_by: str | None = Field(description="What produced the text.")
    external: ArticleTextExternal

    @classmethod
    def of(cls, article: Article) -> "ArticleDetail":
        item = ArticleItem.of(article)
        text, truncated = cap(article.extracted_text or article.snippet)
        return cls(
            **item.model_dump(exclude={"external"}),
            extracted_by=article.extracted_by,
            external=ArticleTextExternal(
                **item.external.model_dump(), text=text, truncated=truncated
            ),
        )


class Digest(BaseModel):
    date: date
    articles: list[ArticleItem] = Field(description="In digest order; empty when there is none.")


class DigestDayItem(BaseModel):
    date: date
    articles: int
    opened: int


class Ranking(BaseModel):
    """How an article reached its place; counts are null when the run did not record them."""

    article_id: int
    position: int | None
    topic: str | None
    rank: int | None = Field(
        description="Place in the whole pool's ranking; null if not near the top."
    )
    pool: int | None = Field(description="Candidates the digest run considered.")
    ranked: int | None
    top: int | None = Field(description="Best ranked candidates kept for the next stages.")
    ranking_method: str | None
    deduplicated_to: int | None
    deduplication_method: str | None
    run_id: str | None
    external: ArticleExternal


class SearchHit(BaseModel):
    similarity: float = Field(description="Cosine similarity to the query, at most 1.")
    article: ArticleItem


class SearchResults(BaseModel):
    model: str
    items: list[SearchHit]


class SourceExternal(BaseModel):
    name: str


class SourceItem(BaseModel):
    id: int
    url: str = Field(description="Feed URL.")
    site_url: str | None
    kind: SourceKind
    status: SourceStatus
    origin: SourceOrigin
    origin_detail: str | None
    note: str | None = Field(description="Why it has its status.")
    created_at: datetime
    health: SourceHealth
    activity: SourceActivity = Field(description="Articles first seen in the last 30 days.")
    external: SourceExternal

    @classmethod
    def of(cls, source: Source, stats: SourceStats | None) -> "SourceItem":
        return cls(
            id=source.id,
            url=source.url,
            site_url=source.site_url,
            kind=source.kind,
            status=source.status,
            origin=source.origin,
            origin_detail=source.origin_detail,
            note=source.note,
            created_at=source.created_at,
            health=SourceHealth(
                fetched_at=source.fetched_at,
                failing_since=source.failing_since,
                permanent_failing_since=source.permanent_failing_since,
                failed_at=source.failed_at,
                fetch_failures=source.fetch_failures,
                fetch_error=source.fetch_error,
            ),
            activity=SourceActivity(
                articles=stats.articles if stats else 0,
                ranked=stats.ranked if stats else 0,
                shown=stats.shown if stats else 0,
                opened=stats.opened if stats else 0,
            ),
            external=SourceExternal(name=source.name),
        )


class SourceList(BaseModel):
    sources: list[SourceItem]


class SurvivalItem(BaseModel):
    origin: SourceOrigin
    adapter: str | None = Field(description="The search adapter, for discovery only.")
    added: int
    enabled: int = Field(description="Read at some point.")
    old_enough: int = Field(description="Enabled and old enough to judge.")
    still_active: int
    shown: int
    opened: int
    opens: int


class Survival(BaseModel):
    rows: list[SurvivalItem]


class OpenCountItem(BaseModel):
    key: str
    shown: int
    opened: int


class OpenStatsExternal(BaseModel):
    by_source: list[OpenCountItem] = Field(description="Keyed by source name.")


class OpenStatsResult(BaseModel):
    days: int
    since: date
    shown: int
    opened: int
    by_topic: list[OpenCountItem]
    external: OpenStatsExternal


class RunExternal(BaseModel):
    stats: dict[str, Any] = Field(description="What the run did; may name sources and titles.")
    error: str | None


class RunItem(BaseModel):
    id: uuid.UUID
    kind: RunKind
    status: RunStatus
    dry_run: bool
    started_at: datetime
    finished_at: datetime | None
    timings: dict[str, Any]
    external: RunExternal

    @classmethod
    def of(cls, run: Run) -> "RunItem":
        return cls(
            id=run.id,
            kind=run.kind,
            status=run.status,
            dry_run=run.dry_run,
            started_at=run.started_at,
            finished_at=run.finished_at,
            timings=run.timings,
            external=RunExternal(stats=run.stats, error=run.error),
        )


class RunList(BaseModel):
    runs: list[RunItem]


class RunSummary(BaseModel):
    id: uuid.UUID
    status: RunStatus
    dry_run: bool
    started_at: datetime
    finished_at: datetime | None

    @classmethod
    def of(cls, run: Run) -> "RunSummary":
        return cls(
            id=run.id,
            status=run.status,
            dry_run=run.dry_run,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )


class ArticleCounts(BaseModel):
    total: int
    shown: int
    opened: int


class StatusResult(BaseModel):
    articles: ArticleCounts
    sources: dict[SourceStatus, int]
    last_digest: date | None
    paused_until: datetime | None
    last_runs: dict[RunKind, RunSummary | None] = Field(description="Null: never ran.")
    embedding_model: str
    embeddings: dict[str, int] = Field(description="Stored vectors by model.")


class DropExternal(BaseModel):
    title: str | None
    kept_title: str | None


class Drop(BaseModel):
    link: str
    reason: str = Field(description="cross_day: shown on an earlier day; same_day: one story.")
    similarity: float
    duplicate_of: str | None = Field(description="The link kept instead, for same-day drops.")
    same_event: float | None = Field(description="The judge's probability, for judged pairs.")
    external: DropExternal


class DedupDecisions(BaseModel):
    run_id: uuid.UUID
    date: str | None
    same_day_method: str | None
    candidates: int | None
    survivors: int | None
    judged_pairs: int | None = Field(description="Grey-zone pairs the judge was asked about.")
    same_day_threshold: float | None
    drops: list[Drop]


class Spending(BaseModel):
    daily_limit_usd: float | None
    monthly_limit_usd: float | None
    spent_today_usd: float
    spent_month_usd: float
    unpriced_runs: int = Field(description="Runs this month with calls that reported no cost.")
    over: bool
    reason: str | None


class RunCost(BaseModel):
    id: uuid.UUID
    kind: RunKind
    dry_run: bool
    started_at: datetime
    cost_usd: float | None = Field(description="Known cost; null when nothing was priced.")
    unpriced_calls: int


class Costs(BaseModel):
    budget: Spending
    recent_runs: list[RunCost]


class InterestItem(BaseModel):
    id: int
    topic: str
    keywords: list[str]
    notes: str
    active: bool

    @classmethod
    def of(cls, interest: Interest) -> "InterestItem":
        return cls(
            id=interest.id,
            topic=interest.topic,
            keywords=list(interest.keywords),
            notes=interest.notes,
            active=interest.active,
        )


class InterestList(BaseModel):
    interests: list[InterestItem]


class ChangeExternal(BaseModel):
    description: str = Field(description="What changed, on one line.")
    reason: str | None


class ChangeItem(BaseModel):
    id: int
    created_at: datetime
    actor: str
    action: str
    entity: str | None = Field(description="e.g. source:12")
    status: ChangeStatus
    external: ChangeExternal

    @classmethod
    def of(cls, change: Change) -> "ChangeItem":
        entity = f"{change.entity_type}:{change.entity_id}" if change.entity_id else None
        return cls(
            id=change.id,
            created_at=change.created_at,
            actor=change.actor,
            action=change.action,
            entity=entity,
            status=change.status,
            external=ChangeExternal(
                description=describe_change(change, width=200), reason=change.reason
            ),
        )


class ChangeList(BaseModel):
    changes: list[ChangeItem]


class PauseState(BaseModel):
    until: datetime | None = Field(description="No digest is built before this; null: not paused.")
