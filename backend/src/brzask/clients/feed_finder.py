"""Finding the feed of a site from any of its pages.

Every candidate is fetched and parsed before it is returned, so a result is a
working feed, never a guess.
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx2

from brzask.clients.feeds import FeedFetcher, FeedRequest, FetchStatus
from brzask.clients.http import ResponseTooLargeError, read_limited
from brzask.log import get_logger
from brzask.urls import host_matches, host_of

log = get_logger(__name__)

FEED_TYPES = {"application/rss+xml", "application/atom+xml", "application/rdf+xml"}
# Where blog engines put their feed: WordPress and Substack /feed, Jekyll /feed.xml,
# Hugo /index.xml, many static generators /rss.xml or /atom.xml.
COMMON_PATHS = ("feed", "rss.xml", "atom.xml", "index.xml", "feed.xml")
MAX_PAGE_BYTES = 5 * 1024 * 1024

# First path segments on github.com that are not repository owners.
GITHUB_RESERVED = frozenset(
    {
        "about", "apps", "collections", "customer-stories", "enterprise", "explore", "features",
        "login", "marketplace", "notifications", "orgs", "pricing", "pulls", "search",
        "settings", "sponsors", "topics", "trending",
    }
)  # fmt: skip
_YOUTUBE_CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
# Most reliable first: on a channel page the first "channelId" can belong to a
# recommended channel, while the canonical link and externalId name the owner;
# video pages carry the owner in a meta tag.
_YOUTUBE_ID_IN_PAGE = (
    re.compile(
        r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"'
    ),
    re.compile(r'"externalId":"(UC[A-Za-z0-9_-]{22})"'),
    re.compile(r'<meta itemprop="(?:channelId|identifier)" content="(UC[A-Za-z0-9_-]{22})"'),
    re.compile(r'"channelId":"(UC[A-Za-z0-9_-]{22})"'),
)
# EU visitors are redirected to a consent page instead of the channel; this
# cookie answers it (checked from an EU address: CONSENT=YES+1 no longer does).
YOUTUBE_CONSENT = {"Cookie": "SOCS=CAI"}


@dataclass(frozen=True, slots=True)
class FoundFeed:
    url: str
    title: str | None
    site_url: str


class FeedFinder:
    def __init__(self, fetcher: FeedFetcher) -> None:
        self.fetcher = fetcher
        self.client = fetcher.client

    def close(self) -> None:
        self.fetcher.close()

    def find(self, url: str) -> FoundFeed | None:
        """The feed for the site of `url`, or None when none can be found."""
        page = _with_scheme(url.strip())
        host = host_of(page)
        if not host:
            return None
        if host_matches(host, "github.com"):
            return self._github(page)
        if host_matches(host, "youtube.com") or host == "youtu.be":
            return self._youtube(page)
        return self._site(page)

    # --- Sites -------------------------------------------------------------------

    def _site(self, page: str) -> FoundFeed | None:
        site_url = _origin(page)
        found = self._feed(page, site_url)  # the URL may be the feed itself
        if found:
            return found
        html, final_url = self._download(page)
        tried = {page}
        if html is not None:
            site_url = _origin(final_url)
            for candidate in alternate_feeds(html, final_url):
                if candidate not in tried:
                    tried.add(candidate)
                    if found := self._feed(candidate, site_url):
                        return found
        for candidate in common_feed_urls(final_url if html is not None else page):
            if candidate not in tried:
                tried.add(candidate)
                if found := self._feed(candidate, site_url):
                    return found
        log.info("no feed found", url=page, tried=len(tried))
        return None

    def _feed(self, url: str, site_url: str) -> FoundFeed | None:
        # Most candidates are expected to fail; that is not worth a warning.
        result = self.fetcher.fetch(FeedRequest(url), log_failure=False)
        if result.status is not FetchStatus.OK:
            return None
        return FoundFeed(url, result.title, site_url)

    def _download(self, url: str, headers: dict[str, str] | None = None) -> tuple[str | None, str]:
        try:
            with self.client.stream(
                "GET", url, headers={"Accept": "text/html,*/*;q=0.5", **(headers or {})}
            ) as response:
                response.raise_for_status()
                body = read_limited(response, MAX_PAGE_BYTES)
                return body.decode(response.encoding or "utf-8", errors="replace"), str(
                    response.url
                )
        except (httpx2.HTTPError, ResponseTooLargeError) as error:
            log.info("page not available", url=url, error=str(error))
            return None, url

    # --- Special cases -----------------------------------------------------------

    def _github(self, page: str) -> FoundFeed | None:
        """A repository's release notes; the URL is built, then checked."""
        segments = [s for s in urlsplit(page).path.split("/") if s]
        if len(segments) < 2 or segments[0].lower() in GITHUB_RESERVED:
            return None
        owner, repo = segments[0], segments[1].removesuffix(".git")
        if segments[-1] == "releases.atom":
            return self._feed(page, f"https://github.com/{owner}/{repo}")
        return self._feed(
            f"https://github.com/{owner}/{repo}/releases.atom", f"https://github.com/{owner}/{repo}"
        )

    def _youtube(self, page: str) -> FoundFeed | None:
        """A channel's video feed, from a channel, handle or video URL."""
        parts = urlsplit(page)
        if parts.path.startswith("/feeds/videos.xml"):
            return self._feed(page, "https://www.youtube.com")
        segments = [s for s in parts.path.split("/") if s]
        if (
            len(segments) >= 2
            and segments[0] == "channel"
            and _YOUTUBE_CHANNEL_ID.match(segments[1])
        ):
            channel_id: str | None = segments[1]
        else:
            html, _ = self._download(page, headers=YOUTUBE_CONSENT)
            channel_id = youtube_channel_id(html or "")
        if channel_id is None:
            return None
        return self._feed(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
            f"https://www.youtube.com/channel/{channel_id}",
        )


# --- Pure helpers --------------------------------------------------------------


class _AlternateLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []  # (href, title)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "link":
            return
        values = {name.lower(): (value or "") for name, value in attrs}
        rels = values.get("rel", "").lower().split()
        kind = values.get("type", "").lower().split(";")[0].strip()
        if "alternate" in rels and kind in FEED_TYPES and values.get("href"):
            self.links.append((values["href"].strip(), values.get("title", "")))


def alternate_feeds(html: str, page_url: str) -> list[str]:
    """Feeds a page announces with `<link rel="alternate">`, comment feeds last."""
    parser = _AlternateLinks()
    parser.feed(html)
    links = [(urljoin(page_url, href), title) for href, title in parser.links]
    links = [(href, title) for href, title in links if urlsplit(href).scheme in {"http", "https"}]

    def is_comments(link: tuple[str, str]) -> bool:
        href, title = link
        return "comment" in title.lower() or "/comments/" in href.lower()

    return list(dict.fromkeys(href for href, _ in sorted(links, key=is_comments)))


def common_feed_urls(page_url: str) -> list[str]:
    """Usual feed locations: under the page's directory first, then at the site root."""
    parts = urlsplit(page_url)
    directory = parts.path if parts.path.endswith("/") else parts.path.rsplit("/", 1)[0] + "/"
    bases = list(dict.fromkeys([directory, "/"]))
    return [
        urlunsplit((parts.scheme, parts.netloc, base + path, "", ""))
        for base in bases
        for path in COMMON_PATHS
    ]


def youtube_channel_id(html: str) -> str | None:
    for pattern in _YOUTUBE_ID_IN_PAGE:
        if match := pattern.search(html):
            return match.group(1)
    return None


def _with_scheme(url: str) -> str:
    return url if re.match(r"^[a-z][a-z0-9+.-]*://", url, re.IGNORECASE) else f"https://{url}"


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
