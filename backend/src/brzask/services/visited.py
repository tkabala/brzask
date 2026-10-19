"""New sources from opened links.

Most opened articles come from a site that is already a source. Aggregators
(Hacker News, Lobsters, Reddit) link elsewhere, and a site reached that way is
a signal: the reader reads things from there, and it is not followed yet.
Its feed becomes a `pending` source, without an LLM judge: there are a few a
week, so a person can look at each one.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from brzask.clients.feed_finder import FeedFinder, FoundFeed
from brzask.clients.feeds import FeedFetcher
from brzask.db.models import Article, SourceOrigin, SourceStatus
from brzask.log import get_logger
from brzask.repositories import ArticleRepository, SourceRepository
from brzask.services.runs import RunContext
from brzask.services.sources import propose_source
from brzask.urls import host_matches, host_of

log = get_logger(__name__)

ACTOR = "pipeline:visited"

# Articles opened in this window are looked at.
OPENED_WINDOW = timedelta(days=30)


class FindsFeeds(Protocol):
    """Finds the feed of a page's site (`FeedFinder`)."""

    def find(self, url: str) -> FoundFeed | None: ...


@dataclass(frozen=True, slots=True)
class NewHost:
    host: str
    link: str  # the most recently opened article from it
    title: str


def related(host: str, known: str) -> bool:
    """One host is the other or a subdomain of it, either way round.

    `blog.example.com` is covered by a source on `example.com`, and a source on
    `blog.example.com` already follows the site behind `example.com` links.
    """
    return host_matches(host, known) or host_matches(known, host)


def new_hosts(opened: Iterable[Article], known_hosts: Iterable[str]) -> list[NewHost]:
    """One entry per host no source covers, from articles newest opened first.

    A link without a host is skipped rather than turned into a broken candidate.
    """
    known = {host for host in known_hosts if host}
    found: dict[str, NewHost] = {}
    for article in opened:
        host = host_of(article.link)
        if not host or host in found or any(related(host, other) for other in known):
            continue
        found[host] = NewHost(host, article.link, article.title)
    return list(found.values())


def known_hosts(urls: Iterable[str | None]) -> set[str]:
    return {host_of(url) for url in urls if url} - {""}


def propose_visited(context: RunContext, finder: FindsFeeds) -> None:
    """Propose a pending source for each new site opened lately; nothing is written in a dry run.

    Every source counts as known whatever its status, so a site that was
    rejected or muted is not proposed again.
    """
    since = context.started_at - OPENED_WINDOW
    with context.sessions.begin() as session:
        sources = SourceRepository(session).find()
        hosts = known_hosts([s.url for s in sources] + [s.site_url for s in sources])
        opened = ArticleRepository(session).opened_since(since)
        candidates = new_hosts(opened, hosts)

    proposed: list[dict[str, str]] = []
    without_feed: list[str] = []
    for candidate in candidates:
        found = finder.find(candidate.link)
        if found is None:
            without_feed.append(candidate.host)
            continue
        if context.dry_run:
            proposed.append({"host": candidate.host, "url": found.url})
            continue
        with context.sessions.begin() as session:
            source = propose_source(
                session,
                found,
                status=SourceStatus.PENDING,
                origin=SourceOrigin.VISITED,
                actor=ACTOR,
                origin_detail=candidate.link,
                note=f'You opened "{candidate.title}" from this site; it is not a source yet.',
            )
            if source is not None:
                proposed.append({"host": candidate.host, "url": source.url, "name": source.name})

    context.stats.update(
        {
            "opened": len(opened),
            "new_hosts": [candidate.host for candidate in candidates],
            "proposed": proposed,
            "without_feed": without_feed,
        }
    )
    log.info(
        "opened links checked",
        opened=len(opened),
        new_hosts=len(candidates),
        proposed=len(proposed),
    )


def run_visited(context: RunContext) -> None:
    """The visited pipeline with a feed finder of its own."""
    finder = FeedFinder(FeedFetcher())
    try:
        propose_visited(context, finder)
    finally:
        finder.close()
