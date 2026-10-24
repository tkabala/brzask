"""Fetching and parsing RSS and Atom feeds.

A feed that fails to download or parse is reported in its result and never
stops the others: one broken source must not cost the day's digest.
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import feedparser
import httpx2

from brzask.clients.http import REQUEST_ERRORS, USER_AGENT, read_limited
from brzask.log import get_logger
from brzask.text import from_struct_time, strip_html
from brzask.urls import is_http_url

log = get_logger(__name__)

# Feeds are fetched in parallel: with 60+ sources, reading them one by one took
# most of a digest run.
WORKERS = 8
TIMEOUT = httpx2.Timeout(30.0, connect=10.0)
# Large feeds are a few MB; anything bigger is not a feed worth reading.
MAX_BYTES = 10 * 1024 * 1024

ACCEPT = (
    "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.1"
)

# What an error response says about why it was refused, logged with the failure:
# YouTube's feed endpoint answered 404 to every followed channel at 06:00 on
# three days in a row while the same requests got 200 later in the day.
DIAGNOSTIC_HEADERS = (
    "Content-Type",
    "Content-Length",
    "Server",
    "Date",
    "Retry-After",
    "Cache-Control",
    "Location",
)
# Error pages carry their own styles: 8 KiB reaches the text after them.
DIAGNOSTIC_BODY_BYTES = 8 * 1024
DIAGNOSTIC_BODY_CHARS = 500


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
    # Whether a failure may go away by itself (429, 5xx, timeouts, network errors),
    # as opposed to a feed that is gone or broken (404, 410, 403, not a feed).
    temporary: bool = False


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

    def fetch(self, request: FeedRequest, *, log_failure: bool = True) -> FeedResult:
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
                try:
                    response.raise_for_status()
                except httpx2.HTTPStatusError as error:
                    return self._failed(
                        request.url,
                        f"{type(error).__name__}: {error}",
                        log_failure,
                        temporary=is_temporary(error),
                        details=response_details(response),
                    )
                body = read_limited(response, MAX_BYTES)
                final_url = str(response.url)
                content_type = response.headers.get("Content-Type", "")
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
        except REQUEST_ERRORS as error:
            return self._failed(
                request.url,
                f"{type(error).__name__}: {error}",
                log_failure,
                temporary=is_temporary(error),
            )

        # The final URL resolves relative links; the content type helps detect the encoding.
        parsed = feedparser.parse(
            body, response_headers={"content-location": final_url, "content-type": content_type}
        )
        if not parsed.get("version") and not parsed.entries:
            reason = parsed.get("bozo_exception") or "no RSS or Atom content"
            return self._failed(request.url, f"not a feed: {reason}", log_failure)
        now = self._now()
        return FeedResult(
            request.url,
            FetchStatus.OK,
            entries=parse_entries(parsed.entries, now),
            title=strip_html(parsed.feed.get("title")) or None,
            etag=etag,
            last_modified=last_modified,
        )

    def _failed(
        self,
        url: str,
        error: str,
        log_failure: bool,
        *,
        temporary: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> FeedResult:
        if log_failure:
            log.warning("feed failed", url=url, error=error, temporary=temporary, **(details or {}))
        return FeedResult(url, FetchStatus.FAILED, error=error, temporary=temporary)


def response_details(response: httpx2.Response) -> dict[str, Any]:
    """The request as sent and the start of the error response, for the failure log."""
    sent = {
        name: response.request.headers[name]
        for name in ("If-None-Match", "If-Modified-Since")
        if name in response.request.headers
    }
    try:
        excerpt = b"".join(_first_bytes(response, DIAGNOSTIC_BODY_BYTES))
        body = strip_html(excerpt.decode("utf-8", "replace"))[:DIAGNOSTIC_BODY_CHARS]
    except REQUEST_ERRORS as error:
        body = f"<unreadable: {type(error).__name__}>"
    return {
        "status_code": response.status_code,
        "http_version": response.http_version,
        "final_url": str(response.url),
        "redirects": [str(hop.url) for hop in response.history],
        "sent": sent,
        "headers": {
            name: response.headers[name] for name in DIAGNOSTIC_HEADERS if name in response.headers
        },
        "body": body,
    }


def _first_bytes(response: httpx2.Response, limit: int) -> Iterator[bytes]:
    size = 0
    for chunk in response.iter_bytes():
        yield chunk[: limit - size]
        size += len(chunk)
        if size >= limit:
            return


def is_temporary(error: Exception) -> bool:
    """Rate limits, server errors, timeouts and network errors may go away by themselves."""
    if isinstance(error, httpx2.HTTPStatusError):
        status = error.response.status_code
        if status == 404 and error.request.url.host == "www.youtube.com":
            # YouTube's feed endpoint answers 404 for every channel during its
            # outages (all 15 followed channels at once, 2026-10-20); a removed
            # channel still goes dead through the longer rule for any failure.
            return True
        return status in {408, 429} or status >= 500
    # A scheme httpx2 cannot speak (a redirect to ftp:) will not start working later.
    return isinstance(error, httpx2.TransportError) and not isinstance(
        error, httpx2.UnsupportedProtocol
    )


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
        if not title or link in seen or not is_http_url(link):
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
