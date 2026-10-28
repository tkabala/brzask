"""The candidate pool: what the day's ranking chooses from.

Fresh entries from every active feed, plus articles seen in the last days that
no digest has shown yet, without stale entries and links already shown. The
pool is capped, taking sources in turns so one chatty feed cannot fill it.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.orm import Session

from brzask.clients.feeds import FeedEntry, FeedRequest, FeedResult, FetchStatus
from brzask.db.models import Article, Source, SourceKind, SourceStatus
from brzask.log import get_logger
from brzask.repositories import ArticleRepository, SourceRepository
from brzask.repositories.articles import NewArticle
from brzask.services.runs import RunContext
from brzask.services.sources import is_release_feed, move_source

log = get_logger(__name__)

ACTOR = "pipeline:digest"

# Feeds bring old entries back to the top; without this cut, stale entries were
# ~89% of the pool (the oldest 340 days old).
MAX_AGE = timedelta(days=10)
# An article seen but not shown stays a candidate for a week.
CARRY_OVER = timedelta(days=7)
# Candidates in the ranking prompt; a week of carry-over alone can pass 300.
POOL_CAP = 200
# Characters of entry text kept as the snippet the ranking prompt shows.
SNIPPET_CHARS = 500


class FeedReader(Protocol):
    """Fetches feeds, returning results in the order of the requests (`FeedFetcher`)."""

    def fetch_all(self, requests: Sequence[FeedRequest]) -> list[FeedResult]: ...


@dataclass(frozen=True, slots=True)
class FeedSource:
    """What the pool needs from a source, readable after its session has closed."""

    id: int
    name: str
    url: str
    release: bool
    etag: str | None = None
    last_modified: str | None = None

    @classmethod
    def of(cls, source: Source) -> "FeedSource":
        return cls(
            id=source.id,
            name=source.name,
            url=source.url,
            # The URL rule covers GitHub release feeds stored with the wrong kind.
            release=source.kind is SourceKind.RELEASE or is_release_feed(source.url),
            etag=source.etag,
            last_modified=source.last_modified,
        )


@dataclass(frozen=True, slots=True)
class Candidate:
    link: str
    title: str
    source_id: int
    source_name: str
    release: bool  # release notes, judged on their content
    snippet: str | None
    published_at: datetime | None  # None when the feed gave no plausible date
    content: str | None = None  # full text from the feed; carried-over articles have none
    article_id: int | None = None  # set once stored; fresh entries have none in a dry run
    rank: int | None = None  # position in the ranking, set for the top candidates
    # Set by extraction, for the top candidates only.
    text: str | None = None  # article text for embeddings and prompts, cut to length
    extracted_by: str | None = None
    embedding: list[float] | None = None


@dataclass(frozen=True, slots=True)
class PoolCounts:
    fresh: int = 0  # entries from today's fetch
    carried_over: int = 0
    stale: int = 0  # published more than MAX_AGE ago
    # In an earlier digest. An article row records one digest appearance, so a
    # link is shown at most once, however long ago that was.
    already_shown: int = 0
    source_inactive: int = 0  # carried over from a source no longer fetched
    unique: int = 0  # candidates after the filters, before the cap


def fresh_candidates(source: FeedSource, entries: Iterable[FeedEntry]) -> list[Candidate]:
    return [
        Candidate(
            link=entry.link,
            title=entry.title,
            source_id=source.id,
            source_name=source.name,
            release=source.release,
            snippet=_snippet(entry.summary or entry.content),
            published_at=entry.published_at,
            content=entry.content,
        )
        for entry in entries
    ]


def carried_candidates(
    articles: Iterable[Article], sources: Mapping[int, FeedSource]
) -> tuple[list[Candidate], int]:
    """Candidates from stored articles, and how many were dropped for an inactive source.

    Carry-over is read by state and age alone, so it knows nothing of sources
    muted or killed since; without this filter their articles keep reaching
    the digest for a week.
    """
    candidates: list[Candidate] = []
    dropped = 0
    for article in articles:
        source = sources.get(article.source_id) if article.source_id is not None else None
        if source is None:
            dropped += 1
            continue
        candidates.append(
            Candidate(
                link=article.link,
                title=article.title,
                source_id=source.id,
                source_name=source.name,
                release=source.release,
                snippet=article.snippet,
                published_at=article.published_at,
                article_id=article.id,
            )
        )
    return candidates, dropped


def filter_candidates(
    fresh: Iterable[Candidate],
    carried: Iterable[Candidate],
    shown_links: set[str],
    now: datetime,
    max_age: timedelta = MAX_AGE,
) -> tuple[list[Candidate], PoolCounts]:
    """Drop stale entries and links already shown; one candidate per link.

    A fresh entry wins over the carried-over copy of the same link, since only
    the fresh one has the feed's full content. An entry without a date is
    kept: a missing date must not remove a candidate.
    """
    cutoff = now - max_age
    by_link: dict[str, Candidate] = {}
    fresh_count = carried_count = stale = already_shown = 0
    for is_fresh, group in ((True, fresh), (False, carried)):
        for candidate in group:
            if is_fresh:
                fresh_count += 1
            else:
                carried_count += 1
            if candidate.link in shown_links:
                already_shown += 1
            elif candidate.published_at is not None and candidate.published_at < cutoff:
                stale += 1
            else:
                by_link.setdefault(candidate.link, candidate)
    counts = PoolCounts(
        fresh=fresh_count,
        carried_over=carried_count,
        stale=stale,
        already_shown=already_shown,
        unique=len(by_link),
    )
    return list(by_link.values()), counts


def take_in_turns(candidates: Iterable[Candidate], cap: int = POOL_CAP) -> list[Candidate]:
    """Up to `cap` candidates, newest of each source first, one source after another.

    Round after round, each source gives its next newest entry, so the cap is
    not used up by the sources that publish the most. Undated entries come last
    within their source.
    """
    by_source: dict[int, list[Candidate]] = {}
    for candidate in candidates:
        by_source.setdefault(candidate.source_id, []).append(candidate)
    oldest = datetime.min.replace(tzinfo=UTC)
    queues = [
        sorted(group, key=lambda c: c.published_at or oldest, reverse=True)
        for group in by_source.values()
    ]
    picked: list[Candidate] = []
    for turn in range(max((len(queue) for queue in queues), default=0)):
        for queue in queues:
            if turn < len(queue):
                picked.append(queue[turn])
                if len(picked) == cap:
                    return picked
    return picked


def gather_candidates(context: RunContext, fetcher: FeedReader) -> list[Candidate]:
    """Fetch the active feeds and build the day's pool.

    Outside a dry run, records each source's fetch outcome and validators and
    stores the pool, so later stages can update candidates by article ID.
    Only the pool is stored: entries cut by the cap come back with the next
    change to their feed.
    """
    now = context.started_at
    with context.sessions.begin() as session:
        sources = {
            source.id: FeedSource.of(source)
            for source in SourceRepository(session).find(SourceStatus.ACTIVE)
        }
        articles = ArticleRepository(session)
        # A repeat of a shown article is as good as shown: the same link from a
        # feed must not take a ranking slot only to be dropped again.
        shown_links = articles.shown_links() | articles.repeat_links()
        carried, source_inactive = carried_candidates(
            articles.carry_over(now - CARRY_OVER), sources
        )

    feeds = list(sources.values())
    with context.stage("fetch"):
        results = fetcher.fetch_all(
            [FeedRequest(feed.url, feed.etag, feed.last_modified) for feed in feeds]
        )
    fresh = [
        candidate
        for feed, result in zip(feeds, results, strict=True)
        for candidate in fresh_candidates(feed, result.entries)
    ]
    candidates, counts = filter_candidates(fresh, carried, shown_links, now)
    pool = take_in_turns(candidates)

    if not context.dry_run:
        with context.sessions.begin() as session:
            _record_fetches(session, feeds, results, now)
            ids = ArticleRepository(session).add_new([_new_article(c) for c in pool])
        pool = [replace(candidate, article_id=ids[candidate.link]) for candidate in pool]

    context.stats["pool"] = {
        "sources": len(feeds),
        "not_modified": sum(result.status is FetchStatus.NOT_MODIFIED for result in results),
        "failed": sum(result.status is FetchStatus.FAILED for result in results),
        **asdict(replace(counts, source_inactive=source_inactive)),
        "candidates": len(pool),
        "releases": sum(candidate.release for candidate in pool),
    }
    log.info("candidate pool built", **context.stats["pool"])
    return pool


def _snippet(text: str | None) -> str | None:
    return text[:SNIPPET_CHARS] if text else None


def _new_article(candidate: Candidate) -> NewArticle:
    return NewArticle(
        link=candidate.link,
        title=candidate.title,
        source_id=candidate.source_id,
        snippet=candidate.snippet,
        published_at=candidate.published_at,
    )


def _record_fetches(
    session: Session, feeds: Sequence[FeedSource], results: Sequence[FeedResult], at: datetime
) -> None:
    repository = SourceRepository(session)
    # Loaded again: a source deleted during the fetch is skipped.
    stored = repository.get_many([feed.id for feed in feeds])
    for feed, result in zip(feeds, results, strict=True):
        source = stored.get(feed.id)
        if source is None:
            continue
        if result.status is FetchStatus.FAILED:
            repository.record_fetch(
                source, at, error=result.error or "unknown error", temporary=result.temporary
            )
            continue
        repository.record_fetch(source, at)
        if result.status is FetchStatus.OK:
            repository.set_fetch_validators(source, result.etag, result.last_modified)
        if result.moved_to:
            move_source(session, source, result.moved_to, actor=ACTOR)
