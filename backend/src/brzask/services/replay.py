"""Replay: past digests chosen again, and the new picks scored by what the reader opened.

For each past digest day, the pool is rebuilt from the articles stored by the
end of that day's run, then ranked, deduplicated and selected again with the
current prompts and model, or with a candidate configuration. The picks are
compared with the reader's opens, next to the digest that was really shown.
Nothing is written: no ranks, no digests, no runs.

What the measure can and cannot say:
- Only shown articles could be opened, so a pick that was never shown counts
  as not opened even if the reader would have liked it. A replay matches the
  real digest's opens by picking the same articles; it cannot beat them by
  much, and a large drop means the change loses what the reader reads.
- Article text and vectors exist only for articles that were in a real top 15;
  others go to deduplication and selection with their feed snippet.
- Interests and reader notes are today's, not those of the replayed day; opens
  in the ranking prompt are only those before the replayed run.
- Each day is replayed against the real history: what the real digests showed
  before it, not what the replay picked, so one article can be picked on two
  replayed days.
- The model does not answer the same prompt the same way twice; compare a
  change with more than one replay of the current setup.
"""

import tomllib
import uuid
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.llm import LLMError
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.db.models import Article, RunKind
from brzask.log import get_logger
from brzask.prompts import Language
from brzask.repositories import ArticleRepository, EmbeddingRepository
from brzask.repositories.articles import DigestRun
from brzask.services.digest import pool, ranking, selection
from brzask.services.digest.dedup import Thresholds, deduplicate_candidates
from brzask.services.digest.pool import (
    Candidate,
    FeedSource,
    carried_candidates,
    filter_candidates,
    take_in_turns,
)
from brzask.services.digest.ranking import ChatModel, RankingLimits, rank_candidates
from brzask.services.digest.selection import SelectionError, select_digest
from brzask.services.errors import ServiceError
from brzask.services.runs import RunContext

log = get_logger(__name__)


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PoolConfig(_Section):
    max_age_days: PositiveInt = pool.MAX_AGE.days
    carry_over_days: PositiveInt = pool.CARRY_OVER.days
    cap: PositiveInt = pool.POOL_CAP


class RankingConfig(_Section):
    rank_limit: PositiveInt = ranking.RANK_LIMIT
    top_n: PositiveInt = ranking.TOP_N
    max_per_source: PositiveInt = ranking.MAX_PER_SOURCE
    min_candidates: PositiveInt = ranking.MIN_CANDIDATES


class DeduplicationConfig(_Section):
    cross_day: float = Field(gt=0, le=1)
    same_day: tuple[float, ...] = Field(min_length=1)


class SelectionConfig(_Section):
    digest_size: PositiveInt = selection.DIGEST_SIZE


class ReplayConfig(_Section):
    """What a replay changes; everything left out keeps the digest's own value.

    Read from TOML with the same sections, e.g. `[ranking]` `top_n = 20`.
    """

    llm_model: str | None = None  # None: LLM_MODEL
    # None: the active model. Another one compares its stored vectors, e.g. after
    # `brzask reembed --no-switch`, to check its thresholds before switching.
    embedding_model: str | None = None
    pool: PoolConfig = PoolConfig()
    ranking: RankingConfig = RankingConfig()
    # None: the embedding model's own thresholds.
    deduplication: DeduplicationConfig | None = None
    selection: SelectionConfig = SelectionConfig()

    @classmethod
    def load(cls, path: Path) -> Self:
        """Read a TOML file; raises ValueError naming what is wrong."""
        try:
            with path.open("rb") as file:
                return cls.model_validate(tomllib.load(file))
        except (OSError, tomllib.TOMLDecodeError, ValidationError) as error:
            raise ValueError(f"{path}: {error}") from error

    def limits(self) -> RankingLimits:
        return RankingLimits(**self.ranking.model_dump())

    def thresholds(self) -> Thresholds | None:
        """The thresholds to try; None keeps the model's own, with a warning if unmeasured."""
        if self.deduplication is None:
            return None
        return Thresholds(self.deduplication.cross_day, self.deduplication.same_day)


@dataclass(frozen=True, slots=True)
class ReplayClients:
    llm: ChatModel
    llm_model: str  # reported with the results
    embedding_model: str  # stored vectors of other models are not used
    language: Language


@dataclass(frozen=True, slots=True)
class ReplayPick:
    article_id: int
    link: str
    title: str  # as written by the selection
    opened: bool
    shown: bool  # in that day's real digest


@dataclass(frozen=True, slots=True)
class DayReplay:
    day: date
    run_at: datetime  # start of the real run; the pool is what was stored by its end
    pool: int
    opened_in_pool: int  # the most opens any selection of this pool could score
    shown: int  # the real digest
    shown_opened: int
    picks: list[ReplayPick] = field(default_factory=list)
    top_with_text: int = 0  # top candidates with stored article text
    stats: dict[str, Any] = field(default_factory=dict)
    usage: list[CallUsage] = field(default_factory=list)
    error: str | None = None

    @property
    def picked_opened(self) -> int:
        return sum(pick.opened for pick in self.picks)

    @property
    def same(self) -> int:
        """Picks that were also in the real digest."""
        return sum(pick.shown for pick in self.picks)


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    days: int  # replayed without error
    failed: int
    picked: int
    picked_opened: int
    shown: int
    shown_opened: int
    opened_in_pool: int
    same: int
    usage: dict[str, Any]


def replay_pool(articles: Iterable[Article], at: datetime, config: PoolConfig) -> list[Candidate]:
    """The pool a run started at `at` would have built from these stored articles.

    `articles` are those first seen in the carry-over window up to the run's
    end and not shown before `at`; stale ones are dropped and the cap applied
    as in a real run.
    """
    stored = list(articles)
    sources = {a.source.id: FeedSource.of(a.source) for a in stored if a.source is not None}
    candidates, _ = carried_candidates(stored, sources)
    kept, _ = filter_candidates([], candidates, set(), at, timedelta(days=config.max_age_days))
    return take_in_turns(kept, config.cap)


def with_stored_text(
    candidates: Sequence[Candidate],
    articles: Mapping[int, Article],
    vectors: Mapping[int, Sequence[float]],
) -> list[Candidate]:
    """Candidates with the text a real run extracted and their stored vectors.

    `vectors` are of one embedding model, the one deduplication compares with.
    """
    result = []
    for candidate in candidates:
        article = articles.get(candidate.article_id) if candidate.article_id else None
        if article is None or candidate.article_id is None:
            result.append(candidate)
            continue
        vector = vectors.get(candidate.article_id)
        result.append(
            replace(
                candidate,
                text=article.extracted_text,
                extracted_by=article.extracted_by,
                embedding=list(vector) if vector is not None else None,
            )
        )
    return result


def replay_day(
    sessions: sessionmaker[Session],
    run: DigestRun,
    clients: ReplayClients,
    config: ReplayConfig,
) -> DayReplay:
    """One day chosen again; a failed model call is reported on the day, not raised."""
    day, run_at = run.day, run.started_at
    since = run_at - timedelta(days=config.pool.carry_over_days)
    with sessions.begin() as session:
        articles = ArticleRepository(session)
        stored = articles.seen_between(since, run_at, run.finished_at)
        # Only what this run showed: a forced run later that day appends
        # articles that were never in this run's pool.
        shown = [a for a in articles.digest(day) if a.shown_at == run_at]
        vectors = EmbeddingRepository(session).of_articles(
            [article.id for article in stored], clients.embedding_model
        )
    by_id = {article.id: article for article in stored}
    candidates = replay_pool(stored, run_at, config.pool)
    result = DayReplay(
        day=day,
        run_at=run_at,
        pool=len(candidates),
        opened_in_pool=sum(
            by_id[c.article_id].opened_at is not None for c in candidates if c.article_id
        ),
        shown=len(shown),
        shown_opened=sum(article.opened_at is not None for article in shown),
    )
    if not candidates:
        return replace(result, error="no stored candidates")

    # A dry run: the stages compute and never write.
    context = RunContext(
        run_id=uuid.uuid4(),
        kind=RunKind.DIGEST,
        started_at=run_at,
        sessions=sessions,
        dry_run=True,
    )
    try:
        top = rank_candidates(context, candidates, clients.llm, config.limits())
        top = with_stored_text(top, by_id, vectors)
        survivors = deduplicate_candidates(
            context, top, clients.embedding_model, config.thresholds()
        )
        picks = select_digest(
            context, survivors, clients.llm, clients.language, config.selection.digest_size
        )
    except (LLMError, SelectionError) as error:
        log.warning("replayed day failed", day=day.isoformat(), error=str(error))
        return replace(
            result,
            stats=context.stats,
            usage=context.usage.calls,
            error=f"{type(error).__name__}: {error}",
        )

    shown_ids = {article.id for article in shown}
    return replace(
        result,
        picks=[
            ReplayPick(
                article_id=article_id,
                link=pick.candidate.link,
                title=pick.title,
                opened=by_id[article_id].opened_at is not None,
                shown=article_id in shown_ids,
            )
            for pick in picks
            if (article_id := pick.candidate.article_id) is not None
        ],
        top_with_text=sum(candidate.text is not None for candidate in top),
        stats=context.stats,
        usage=context.usage.calls,
    )


def replay(
    sessions: sessionmaker[Session],
    clients: ReplayClients,
    since: date,
    config: ReplayConfig | None = None,
    workers: int = 1,
) -> list[DayReplay]:
    """Every digest day from `since` on, chosen again, oldest first.

    Days run in parallel on `workers` threads: each waits on two model calls.
    """
    config = config or ReplayConfig()
    with sessions.begin() as session:
        stored = EmbeddingRepository(session).counts_by_model()
        runs = ArticleRepository(session).digest_runs(since)
    if stored and clients.embedding_model not in stored:
        # Deduplication would compare nothing and the replay would look valid.
        raise ServiceError(
            f"no vectors of {clients.embedding_model} are stored "
            "(brzask reembed --model ... --no-switch computes them)"
        )
    log.info("replaying digests", days=len(runs), since=since.isoformat())
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(
            executor.map(
                lambda run: replay_day(sessions, run, clients, config),
                runs,
            )
        )


def summarize(days: Sequence[DayReplay]) -> ReplaySummary:
    """Totals over the days replayed without error, so both sides cover the same days."""
    done = [day for day in days if day.error is None]
    meter = UsageMeter()
    for day in days:
        for call in day.usage:
            meter.add(call)
    return ReplaySummary(
        days=len(done),
        failed=len(days) - len(done),
        picked=sum(len(day.picks) for day in done),
        picked_opened=sum(day.picked_opened for day in done),
        shown=sum(day.shown for day in done),
        shown_opened=sum(day.shown_opened for day in done),
        opened_in_pool=sum(day.opened_in_pool for day in done),
        same=sum(day.same for day in done),
        usage=meter.summary(),
    )


def report(
    days: Sequence[DayReplay], clients: ReplayClients, config: ReplayConfig
) -> dict[str, Any]:
    """Everything about a replay as JSON-ready data."""
    return {
        "llm_model": clients.llm_model,
        "embedding_model": clients.embedding_model,
        "config": config.model_dump(mode="json"),
        "summary": asdict(summarize(days)),
        "days": [
            {
                "day": day.day.isoformat(),
                "run_at": day.run_at.isoformat(),
                "pool": day.pool,
                "opened_in_pool": day.opened_in_pool,
                "shown": day.shown,
                "shown_opened": day.shown_opened,
                "picked": len(day.picks),
                "picked_opened": day.picked_opened,
                "same": day.same,
                "top_with_text": day.top_with_text,
                "error": day.error,
                "picks": [asdict(pick) for pick in day.picks],
                "stats": day.stats,
            }
            for day in days
        ],
    }
