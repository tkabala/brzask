from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest

from brzask import PROJECT_URL
from brzask.clients.feeds import (
    MAX_BYTES,
    FeedFetcher,
    FeedRequest,
    FeedResult,
    FetchStatus,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "feeds"
NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)
BASE = "https://feeds.test"


class FakeServer:
    """Serves fixture files by path; records request headers."""

    def __init__(self, routes: dict[str, httpx2.Response | Exception] | None = None) -> None:
        self.routes = routes or {}
        self.requests: list[httpx2.Request] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path = request.url.path
        if path in self.routes:
            route = self.routes[path]
            if isinstance(route, Exception):
                raise route
            return route
        fixture = FIXTURES / path.lstrip("/")
        if not fixture.exists():
            return httpx2.Response(404)
        return httpx2.Response(
            200,
            content=fixture.read_bytes(),
            headers={"Content-Type": "application/xml", "ETag": '"v1"'},
        )

    def fetcher(self) -> FeedFetcher:
        fetcher = FeedFetcher(now=lambda: NOW)
        fetcher.client = httpx2.Client(
            transport=httpx2.MockTransport(self.handle),
            headers=fetcher.client.headers,
            follow_redirects=True,
        )
        return fetcher


def fetch(name: str, server: FakeServer | None = None) -> FeedResult:
    return (server or FakeServer()).fetcher().fetch(FeedRequest(f"{BASE}/{name}"))


# --- RSS -----------------------------------------------------------------------


def test_rss_entries_are_cleaned() -> None:
    result = fetch("rss2.xml")

    assert result.status is FetchStatus.OK
    assert result.title == "Example & Co. Blog"
    assert result.etag == '"v1"'
    first = result.entries[0]
    assert first.link == "https://blog.example.com/posts/postgres-18"
    assert first.title == "Postgres 18 released"
    assert first.summary == "Short summary of the release."
    assert first.content == "What is new Asynchronous I/O & virtual generated columns. One Two"
    assert first.published_at == datetime(2026, 10, 16, 7, 30, tzinfo=UTC)


def test_rss_keeps_only_usable_entries() -> None:
    links = [entry.link for entry in fetch("rss2.xml").entries]

    # Repeated link, missing link, blank title and mailto: are dropped.
    assert links == [
        "https://blog.example.com/posts/postgres-18",
        "https://blog.example.com/posts/broken-date",
        "https://blog.example.com/posts/future",
        "https://blog.example.com/posts/dc-date",
        "https://feeds.test/posts/relative",
    ]


def test_broken_and_implausible_dates_are_unknown() -> None:
    by_title = {entry.title: entry for entry in fetch("rss2.xml").entries}

    assert by_title["Broken date"].published_at is None
    assert by_title["From the future"].published_at is None
    assert by_title["Dublin Core date only"].published_at == datetime(2026, 10, 15, 8, tzinfo=UTC)
    assert by_title["Relative link"].published_at is None


def test_relative_links_resolve_against_the_final_url() -> None:
    server = FakeServer({"/old-feed": httpx2.Response(301, headers={"Location": "/rss2.xml"})})

    result = fetch("old-feed", server)

    assert "https://feeds.test/posts/relative" in [entry.link for entry in result.entries]


def test_encoding_from_the_xml_declaration() -> None:
    [entry] = fetch("latin2.xml").entries

    assert entry.title == "Zażółć gęślą jaźń"


def test_truncated_feed_keeps_complete_entries() -> None:
    result = fetch("truncated.xml")

    assert result.status is FetchStatus.OK
    assert [entry.title for entry in result.entries] == ["Complete entry"]


# --- Atom ----------------------------------------------------------------------


def test_atom_entries() -> None:
    result = fetch("atom.xml")

    assert result.title == "Example Releases"
    major, patch = result.entries
    assert major.title == "v2.0.0"
    assert major.summary == "Major release."
    assert major.content == "New plugin API Faster startup"
    assert major.published_at == datetime(2026, 10, 17, 8, tzinfo=UTC)  # published wins
    assert patch.title == "v1.9.1 (patch)"
    assert patch.link == "https://feeds.test/releases/v1.9.1"
    assert patch.published_at == datetime(2026, 10, 10, 8, tzinfo=UTC)  # falls back to updated
    assert patch.content is None


# --- Empty and broken feeds ----------------------------------------------------


@pytest.mark.parametrize("name", ["empty_rss.xml", "empty_atom.xml"])
def test_empty_feeds_are_ok_with_no_entries(name: str) -> None:
    result = fetch(name)

    assert result.status is FetchStatus.OK
    assert result.entries == []


def test_an_html_page_is_not_a_feed() -> None:
    result = fetch("not_a_feed.html")

    assert result.status is FetchStatus.FAILED
    assert result.error is not None
    assert result.error.startswith("not a feed")


@pytest.mark.parametrize(
    ("route", "error"),
    [
        (httpx2.Response(404), "HTTPStatusError"),
        (httpx2.Response(500), "HTTPStatusError"),
        (httpx2.ConnectError("refused"), "ConnectError"),
        (httpx2.ReadTimeout("slow"), "ReadTimeout"),
    ],
)
def test_download_failures_are_reported(route: httpx2.Response | Exception, error: str) -> None:
    result = fetch("broken", FakeServer({"/broken": route}))

    assert result.status is FetchStatus.FAILED
    assert result.error is not None
    assert result.error.startswith(error)
    assert result.entries == []


def test_oversized_responses_are_refused() -> None:
    huge = httpx2.Response(200, content=b"<rss>" + b" " * (MAX_BYTES + 1))

    result = fetch("huge", FakeServer({"/huge": huge}))

    assert result.status is FetchStatus.FAILED
    assert "larger than" in (result.error or "")


# --- Requests ------------------------------------------------------------------


def test_requests_identify_brzask() -> None:
    server = FakeServer()

    fetch("rss2.xml", server)

    [request] = server.requests
    assert request.headers["User-Agent"].startswith("brzask/")
    assert PROJECT_URL in request.headers["User-Agent"]
    assert "application/rss+xml" in request.headers["Accept"]
    assert "If-None-Match" not in request.headers


def test_conditional_get() -> None:
    server = FakeServer({"/cached.xml": httpx2.Response(304)})
    fetcher = server.fetcher()

    result = fetcher.fetch(
        FeedRequest(
            f"{BASE}/cached.xml", etag='"v1"', last_modified="Sat, 17 Oct 2026 06:00:00 GMT"
        )
    )

    assert result.status is FetchStatus.NOT_MODIFIED
    assert result.entries == []
    assert (result.etag, result.last_modified) == ('"v1"', "Sat, 17 Oct 2026 06:00:00 GMT")
    [request] = server.requests
    assert request.headers["If-None-Match"] == '"v1"'
    assert request.headers["If-Modified-Since"] == "Sat, 17 Oct 2026 06:00:00 GMT"


def test_fetch_all_keeps_the_order_and_isolates_failures() -> None:
    server = FakeServer({"/down.xml": httpx2.ConnectError("refused")})
    names = ["atom.xml", "down.xml", "rss2.xml", "empty_rss.xml"] * 3

    results = server.fetcher().fetch_all([FeedRequest(f"{BASE}/{name}") for name in names])

    assert [result.url for result in results] == [f"{BASE}/{name}" for name in names]
    assert [result.status for result in results[:4]] == [
        FetchStatus.OK,
        FetchStatus.FAILED,
        FetchStatus.OK,
        FetchStatus.OK,
    ]
    assert len(server.requests) == len(names)
