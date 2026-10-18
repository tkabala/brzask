"""Fetching and parsing RSS and Atom feeds.

A feed that fails to download or parse is reported in its result and never
stops the others: one broken source must not cost the day's digest.
"""

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

import feedparser
import httpx2

from brzask import PROJECT_URL, __version__
from brzask.log import get_logger
from brzask.text import from_struct_time, strip_html

log = get_logger(__name__)

# Feeds are fetched in parallel: with 60+ sources, reading them one by one took
# most of a digest run.
WORKERS = 8
TIMEOUT = httpx2.Timeout(30.0, connect=10.0)
# Large feeds are a few MB; anything bigger is not a feed worth reading.
MAX_BYTES = 10 * 1024 * 1024

USER_AGENT = f"brzask/{__version__} (+{PROJECT_URL})"
ACCEPT = (
    "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.1"
)


@dataclass(frozen=True, slots=True)
class FeedRequest:
    url: str
    # Validators from the previous successful fetch, for a conditional GET.
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class FeedEntry:
    link: str
    title: str
    summary: str | None  # plain text of the entry summary or description
    content: str | None  # plain text of the full content (content:encoded, Atom content)
    published_at: datetime | None  # None when the feed gives no plausible date


class FetchStatus(StrEnum):
    OK = "ok"
    NOT_MODIFIED = "not_modified"  # 304: nothing new since the last fetch
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FeedResult:
    url: str
    status: FetchStatus
    entries: list[FeedEntry] = field(default_factory=list)
    title: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None


class FeedTooLargeError(Exception):
    pass


class FeedFetcher:
    def __init__(
        self,
        client: httpx2.Client | None = None,
        *,
        workers: int = WORKERS,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client = client or httpx2.Client(
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": ACCEPT},
        )
        self.workers = workers
        self._now = now

    def close(self) -> None:
        self.client.close()

    def fetch_all(self, requests: Sequence[FeedRequest]) -> list[FeedResult]:
        """Results in the same order as `requests`."""
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            results = list(pool.map(self.fetch, requests))
        log.info(
            "feeds fetched",
            feeds=len(results),
            entries=sum(len(result.entries) for result in results),
            not_modified=sum(result.status is FetchStatus.NOT_MODIFIED for result in results),
            failed=sum(result.status is FetchStatus.FAILED for result in results),
        )
        return results

    def fetch(self, request: FeedRequest) -> FeedResult:
        headers = {}
        if request.etag:
            headers["If-None-Match"] = request.etag
        if request.last_modified:
            headers["If-Modified-Since"] = request.last_modified
        try:
            with self.client.stream("GET", request.url, headers=headers) as response:
                if response.status_code == 304:
                    return FeedResult(
                        request.url,
                        FetchStatus.NOT_MODIFIED,
                        etag=request.etag,
                        last_modified=request.last_modified,
                    )
                response.raise_for_status()
                body = _read_limited(response)
                final_url = str(response.url)
                content_type = response.headers.get("Content-Type", "")
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
        except (httpx2.HTTPError, FeedTooLargeError) as error:
            return self._failed(request.url, f"{type(error).__name__}: {error}")

        # The final URL resolves relative links; the content type helps detect the encoding.
        parsed = feedparser.parse(
            body, response_headers={"content-location": final_url, "content-type": content_type}
        )
        if not parsed.get("version") and not parsed.entries:
            reason = parsed.get("bozo_exception") or "no RSS or Atom content"
            return self._failed(request.url, f"not a feed: {reason}")
        now = self._now()
        return FeedResult(
            request.url,
            FetchStatus.OK,
            entries=parse_entries(parsed.entries, now),
            title=strip_html(parsed.feed.get("title")) or None,
            etag=etag,
            last_modified=last_modified,
        )

    def _failed(self, url: str, error: str) -> FeedResult:
        log.warning("feed failed", url=url, error=error)
        return FeedResult(url, FetchStatus.FAILED, error=error)


def parse_entries(entries: Sequence[Mapping[str, Any]], now: datetime) -> list[FeedEntry]:
    """Usable entries: an http(s) link and a title; the first of repeated links wins."""
    seen: set[str] = set()
    parsed: list[FeedEntry] = []
    for raw in entries:
        # A plain copy holds only the keys the feed had: feedparser's own lookup
        # maps a missing published date to the updated one, with a deprecation
        # warning; the fallback is explicit in `_published` instead.
        entry = dict(raw)
        link = str(entry.get("link") or "").strip()
        title = strip_html(entry.get("title"))
        if not title or link in seen or urlsplit(link).scheme not in {"http", "https"}:
            continue
        seen.add(link)
        parsed.append(
            FeedEntry(
                link=link,
                title=title,
                summary=strip_html(entry.get("summary")) or None,
                content=_content(entry),
                published_at=_published(entry, now),
            )
        )
    return parsed


def _content(entry: Mapping[str, Any]) -> str | None:
    """The longest content block; feeds may carry several (e.g. text and HTML)."""
    blocks = [strip_html(block.get("value")) for block in entry.get("content") or []]
    longest = max(blocks, key=len, default="")
    return longest or None


def _published(entry: Mapping[str, Any], now: datetime) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        moment = from_struct_time(entry.get(key), now)
        if moment is not None:
            return moment
    return None


def _read_limited(response: httpx2.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > MAX_BYTES:
            raise FeedTooLargeError(f"larger than {MAX_BYTES // (1024 * 1024)} MB")
        chunks.append(chunk)
    return b"".join(chunks)
