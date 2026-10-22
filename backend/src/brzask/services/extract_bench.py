"""Extraction benchmark: every extractor on the same sample of stored links.

Each extractor runs on its own (not as a chain) through the same rules as a
digest run: robots.txt, the per-site rules and the one rule for usable text.
The sample is spread over sites, and the sampled sources' feeds are fetched
again so the `feed` extractor gets the content it would have had.

Read the results per site as much as in total: an extractor that fails on one
large site looks worse overall than it is.
"""

import math
import random
import re
import statistics
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.extractors import ExtractionInput, Extractor, ExtractorChain, Outcome
from brzask.clients.extractors.base import BLOCK_PAGE_MAX_CHARS, BLOCK_PHRASES
from brzask.clients.extractors.chain import RobotsCheck
from brzask.clients.feeds import FeedRequest
from brzask.db.models import Article
from brzask.log import get_logger
from brzask.repositories import ArticleRepository
from brzask.services.digest.pool import FeedReader
from brzask.urls import host_of

log = get_logger(__name__)

# Usable text shorter than this share of the longest usable text for the same
# link: either it misses part of the article or the longer one keeps the page
# around it (navigation, related links); hosted readers often do. Look at both.
SHORT_SHARE = 0.5
# A feed text this much shorter than the page is a teaser; this close to it, the full article.
TEASER_RATIO = 2.0
FULL_RATIO = 1.25
SKIPPED = {Outcome.SKIPPED_RULE, Outcome.SKIPPED_ROBOTS}

# Markdown images and link targets: readers keep every URL, which makes their
# text look longer than the article is. Lengths are compared in words without them.
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_WORD = re.compile(r"\w+")


def words(text: str) -> int:
    """Words of `text`, leaving out Markdown images, link targets and bare URLs."""
    plain = _URL.sub(" ", _LINK.sub(r"\1", _IMAGE.sub(" ", text)))
    return len(_WORD.findall(plain))


@dataclass(frozen=True, slots=True)
class BenchItem:
    url: str
    host: str
    source_url: str
    snippet: str | None = None
    feed_content: str | None = None  # set once the source's feed is fetched again
    title: str | None = None


@dataclass(frozen=True, slots=True)
class BenchAttempt:
    url: str
    host: str
    extractor: str
    outcome: Outcome
    chars: int = 0  # of the text the extractor returned, usable or not
    words: int = 0  # of usable text, see `words`
    duration_ms: int = 0
    error: str | None = None
    tokens: int | None = None  # billed by a hosted reader
    block_phrase: bool = False  # usable text that contains a block phrase (a long page)


@dataclass(frozen=True, slots=True)
class ExtractorSummary:
    extractor: str
    tried: int  # not skipped by a site rule or robots.txt
    usable: int
    too_short: int
    blocked: int
    empty: int
    failed: int
    skipped: int
    median_chars: int  # of usable texts
    median_words: int
    median_ms: int  # of tried attempts
    p90_ms: int
    shorter_than_best: int  # usable, but under SHORT_SHARE of the most words for the link
    only_usable: int  # links where no other extractor got usable text
    long_with_block_phrase: int
    tokens: int


@dataclass(frozen=True, slots=True)
class FeedCheck:
    """How well FEED_MIN_CHARS tells full feed content from a teaser."""

    with_content: int  # items whose feed carried content
    compared: int  # ...and some page extractor got usable text
    accepted_full: int  # feed text accepted, about as long as the page
    accepted_teaser: int  # feed text accepted, but the page is much longer
    rejected_full: int  # feed text rejected as too short, yet as long as the page
    rejected_teaser: int  # feed text rejected, and the page is much longer
    # (link, feed chars, feed words, page words), for the JSON report
    pairs: list[tuple[str, int, int, int]]


def sample_items(
    articles: Iterable[Article], size: int, per_host: int, rng: random.Random
) -> list[BenchItem]:
    """Up to `size` links in random order, at most `per_host` from one site."""
    candidates = list(articles)
    rng.shuffle(candidates)
    taken: dict[str, int] = defaultdict(int)
    items: list[BenchItem] = []
    for article in candidates:
        host = host_of(article.link)
        if article.source is None or not host or taken[host] >= per_host:
            continue
        taken[host] += 1
        items.append(
            BenchItem(article.link, host, article.source.url, article.snippet, title=article.title)
        )
        if len(items) == size:
            break
    return items


def load_sample(
    sessions: sessionmaker[Session], since: datetime, size: int, per_host: int, seed: int
) -> list[BenchItem]:
    with sessions.begin() as session:
        articles = ArticleRepository(session).first_seen_since(since)
        return sample_items(articles, size, per_host, random.Random(seed))  # noqa: S311  (a sample, not a secret)


def with_feed_content(items: Sequence[BenchItem], feeds: FeedReader) -> list[BenchItem]:
    """Items with the content their feed carries now; links no longer in the feed get none."""
    urls = sorted({item.source_url for item in items})
    results = feeds.fetch_all([FeedRequest(url) for url in urls])
    content = {
        entry.link: entry.content for result in results for entry in result.entries if entry.content
    }
    return [replace(item, feed_content=content.get(item.url)) for item in items]


def run_bench(
    items: Sequence[BenchItem],
    extractors: Sequence[Extractor],
    robots: RobotsCheck | None,
    workers: int = 4,
    intervals: Mapping[str, float] | None = None,
) -> list[BenchAttempt]:
    """Every extractor on every item; `intervals` paces an extractor (seconds between calls).

    A paced extractor runs one call at a time, so the wait never counts as latency.
    """
    attempts: list[BenchAttempt] = []
    for extractor in extractors:
        chain = ExtractorChain([extractor], robots)
        interval = (intervals or {}).get(extractor.name, 0.0)
        log.info("benchmarking extractor", extractor=extractor.name, items=len(items))
        if interval > 0:
            for number, item in enumerate(items):
                if number:
                    time.sleep(interval)
                attempts.append(_attempt(chain, item))
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                attempts.extend(executor.map(_attempt, [chain] * len(items), items))
    return attempts


def _attempt(chain: ExtractorChain, item: BenchItem) -> BenchAttempt:
    result = chain.extract(ExtractionInput(item.url, item.snippet, item.feed_content, item.title))
    (attempt,) = result.attempts
    usable = attempt.outcome is Outcome.USABLE and result.extracted is not None
    text = result.extracted.text if usable and result.extracted else ""
    return BenchAttempt(
        url=item.url,
        host=item.host,
        extractor=attempt.extractor,
        outcome=attempt.outcome,
        chars=attempt.chars,
        words=words(text),
        duration_ms=attempt.duration_ms,
        error=attempt.error,
        tokens=result.extracted.tokens if usable and result.extracted else None,
        block_phrase=len(text) > BLOCK_PAGE_MAX_CHARS and bool(BLOCK_PHRASES.search(text)),
    )


def summarize(attempts: Sequence[BenchAttempt]) -> list[ExtractorSummary]:
    """One row per extractor, in the order they ran."""
    best: dict[str, int] = defaultdict(int)
    usable_by: dict[str, set[str]] = defaultdict(set)
    for attempt in attempts:
        if attempt.outcome is Outcome.USABLE:
            best[attempt.url] = max(best[attempt.url], attempt.words)
            usable_by[attempt.url].add(attempt.extractor)

    rows = []
    for name, group in _by_extractor(attempts).items():
        tried = [a for a in group if a.outcome not in SKIPPED]
        usable = [a for a in tried if a.outcome is Outcome.USABLE]
        durations = sorted(a.duration_ms for a in tried)
        rows.append(
            ExtractorSummary(
                extractor=name,
                tried=len(tried),
                usable=len(usable),
                too_short=_count(tried, Outcome.TOO_SHORT),
                blocked=_count(tried, Outcome.BLOCKED),
                empty=_count(tried, Outcome.EMPTY),
                failed=_count(tried, Outcome.FAILED),
                skipped=len(group) - len(tried),
                median_chars=_median([a.chars for a in usable]),
                median_words=_median([a.words for a in usable]),
                median_ms=_median(durations),
                p90_ms=_percentile(durations, 0.9),
                shorter_than_best=sum(a.words < SHORT_SHARE * best[a.url] for a in usable),
                only_usable=sum(usable_by[a.url] == {name} for a in usable),
                long_with_block_phrase=sum(a.block_phrase for a in usable),
                tokens=sum(a.tokens or 0 for a in usable),
            )
        )
    return rows


def by_site(attempts: Sequence[BenchAttempt]) -> dict[str, dict[str, tuple[int, int]]]:
    """Per site and extractor: (usable, tried), sites with the most links first."""
    sites: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for attempt in attempts:
        if attempt.outcome in SKIPPED:
            continue
        counts = sites[attempt.host][attempt.extractor]
        counts[0] += attempt.outcome is Outcome.USABLE
        counts[1] += 1
    ordered = sorted(
        sites.items(), key=lambda site: (-max(c[1] for c in site[1].values()), site[0])
    )
    return {host: {name: (c[0], c[1]) for name, c in row.items()} for host, row in ordered}


def check_feed_threshold(
    items: Sequence[BenchItem], attempts: Sequence[BenchAttempt], min_chars: int
) -> FeedCheck:
    """Feed content against the page text a chain would have used instead, in words.

    The page text is that of the first page extractor, in the order they ran,
    that got usable text: the longest one would favour readers that keep the
    whole page around the article. Feed content is accepted by its length in
    characters (`min_chars`), as the feed extractor does.
    """
    page: dict[str, int] = {}
    for attempt in attempts:
        if attempt.extractor != "feed" and attempt.outcome is Outcome.USABLE:
            page.setdefault(attempt.url, attempt.words)
    with_content = [item for item in items if item.feed_content and item.feed_content.strip()]
    measured = [
        (item.url, len((item.feed_content or "").strip()), words(item.feed_content or ""))
        for item in with_content
        if item.url in page
    ]
    accepted = [(feed, page[url]) for url, chars, feed in measured if chars >= min_chars]
    rejected = [(feed, page[url]) for url, chars, feed in measured if chars < min_chars]
    return FeedCheck(
        with_content=len(with_content),
        compared=len(measured),
        accepted_full=sum(best <= FULL_RATIO * feed for feed, best in accepted),
        accepted_teaser=sum(best >= TEASER_RATIO * feed for feed, best in accepted),
        rejected_full=sum(best <= FULL_RATIO * feed for feed, best in rejected),
        rejected_teaser=sum(best >= TEASER_RATIO * feed for feed, best in rejected),
        pairs=sorted((url, chars, feed, page[url]) for url, chars, feed in measured),
    )


def report(
    items: Sequence[BenchItem], attempts: Sequence[BenchAttempt], feed_check: FeedCheck
) -> dict[str, Any]:
    """Everything as JSON-ready data."""
    return {
        "items": len(items),
        "sites": len({item.host for item in items}),
        "extractors": [asdict(row) for row in summarize(attempts)],
        "sites_by_extractor": {
            host: {name: {"usable": u, "tried": t} for name, (u, t) in row.items()}
            for host, row in by_site(attempts).items()
        },
        "feed_threshold": asdict(feed_check),
        "attempts": [asdict(attempt) for attempt in attempts],
    }


def _by_extractor(attempts: Iterable[BenchAttempt]) -> dict[str, list[BenchAttempt]]:
    groups: dict[str, list[BenchAttempt]] = {}
    for attempt in attempts:
        groups.setdefault(attempt.extractor, []).append(attempt)
    return groups


def _count(attempts: Iterable[BenchAttempt], outcome: Outcome) -> int:
    return sum(attempt.outcome is outcome for attempt in attempts)


def _median(values: Sequence[int]) -> int:
    return round(statistics.median(values)) if values else 0


def _percentile(values: Sequence[int], share: float) -> int:
    """Nearest-rank percentile of sorted `values`; 0 when empty."""
    if not values:
        return 0
    return values[max(0, math.ceil(share * len(values)) - 1)]
