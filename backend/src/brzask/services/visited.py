"""New sources from opened links.

Most opened articles come from a site that is already a source. Aggregators
(Hacker News, Lobsters, Reddit) link elsewhere, and a site reached that way is
a signal: the reader reads things from there, and it is not followed yet.
Its feed becomes a `pending` source, without an LLM judge: there are a few a
week, so a person can look at each one.

On GitHub and YouTube one host holds many feeds (a repository's releases, a
channel's videos), so there the repository or the video counts as the site.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from urllib.parse import urlsplit

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
    host: str  # the site: a host, a GitHub repository or a YouTube video
    link: str  # the most recently opened article from it
    title: str


def related(host: str, known: str) -> bool:
    """One host is the other or a subdomain of it, either way round.

    `blog.example.com` is covered by a source on `example.com`, and a source on
    `blog.example.com` already follows the site behind `example.com` links.
    """
    return host_matches(host, known) or host_matches(known, host)


def site_of(url: str) -> str:
    """The site a link belongs to; empty for something that is not a URL.

    The host, except on GitHub, where it is the repository (`github.com/owner/repo`),
    and on YouTube, where it is the video or channel page: which channel a
    video belongs to is only known once its page is fetched.
    """
    host = host_of(url)
    if host == "github.com":
        segments = [s for s in urlsplit(url).path.split("/") if s][:2]
        return "/".join([host, *segments])
    if host_matches(host, "youtube.com") or host == "youtu.be":
        parts = urlsplit(url)
        return f"{host}{parts.path}" + (f"?{parts.query}" if parts.query else "")
    return host


def new_hosts(opened: Iterable[Article], known_sites: Iterable[str]) -> list[NewHost]:
    """One entry per site no source covers, from articles newest opened first.

    An article that links to the site of its own source (a channel's video, a
    repository's release) came through that source's feed and is skipped. So
    is a link without a host, rather than turned into a broken candidate.
    """
    known = {site for site in known_sites if site}
    found: dict[str, NewHost] = {}
    for article in opened:
        site = site_of(article.link)
        if not site or site in found or _from_own_source(article):
            continue
        if any(related(site, other) for other in known):
            continue
        found[site] = NewHost(site, article.link, article.title)
    return list(found.values())


def known_hosts(urls: Iterable[str | None]) -> set[str]:
    return {host_of(url) for url in urls if url} - {""}


def known_sites(urls: Iterable[str | None]) -> set[str]:
    """The sites of source and site URLs, as `site_of` gives them."""
    return {site_of(url) for url in urls if url} - {""}


def _from_own_source(article: Article) -> bool:
    source = article.source
    if source is None:
        return False
    host = host_of(article.link)
    return any(related(host, other) for other in known_hosts([source.url, source.site_url]))


def propose_visited(context: RunContext, finder: FindsFeeds) -> None:
    """Propose a pending source for each new site opened lately; nothing is written in a dry run.

    Every source counts as known whatever its status, so a site that was
    rejected or muted is not proposed again.
    """
    since = context.started_at - OPENED_WINDOW
    with context.sessions.begin() as session:
        sources = SourceRepository(session).find()
        sites = known_sites([s.url for s in sources] + [s.site_url for s in sources])
        opened = ArticleRepository(session).opened_since(since)
        candidates = new_hosts(opened, sites)

    proposed: list[dict[str, str]] = []
    without_feed: list[str] = []
    feeds: set[str] = set()
    for candidate in candidates:
        found = finder.find(candidate.link)
        if found is None:
            without_feed.append(candidate.host)
            continue
        if found.url in feeds:  # two videos of one channel
            continue
        feeds.add(found.url)
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
