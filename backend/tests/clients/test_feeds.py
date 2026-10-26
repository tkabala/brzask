from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from structlog.testing import capture_logs

from brzask import PROJECT_URL
from brzask.clients.extractors.base import BLOCK_PAGE_MAX_CHARS
from brzask.clients.feeds import (
    DIAGNOSTIC_BODY_CHARS,
    MAX_BYTES,
    FeedFetcher,
    FeedRequest,
    FeedResult,
    FetchStatus,
    is_temporary,
    parse_entries,
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


def test_malformed_links_are_skipped() -> None:
    entries = [
        {"link": "http://[oops/post", "title": "Malformed"},
        {"link": "https:///no-host", "title": "No host"},
        {"link": "https://blog.example.com/ok", "title": "Fine"},
    ]

    assert [entry.title for entry in parse_entries(entries, NOW)] == ["Fine"]


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
    assert not result.temporary


@pytest.mark.parametrize(
    ("route", "error", "temporary"),
    [
        (httpx2.Response(404), "HTTPStatusError", False),
        (httpx2.Response(410), "HTTPStatusError", False),
        (httpx2.Response(403), "HTTPStatusError", False),
        (httpx2.Response(429), "HTTPStatusError", True),
        (httpx2.Response(500), "HTTPStatusError", True),
        (httpx2.Response(503), "HTTPStatusError", True),
        (httpx2.ConnectError("refused"), "ConnectError", True),
        (httpx2.ReadTimeout("slow"), "ReadTimeout", True),
        (httpx2.UnsupportedProtocol("ftp"), "UnsupportedProtocol", False),
    ],
)
def test_download_failures_are_reported(
    route: httpx2.Response | Exception, error: str, temporary: bool
) -> None:
    result = fetch("broken", FakeServer({"/broken": route}))

    assert result.status is FetchStatus.FAILED
    assert result.error is not None
    assert result.error.startswith(error)
    assert result.temporary is temporary
    assert result.entries == []


@pytest.mark.parametrize(
    ("url", "temporary"),
    [
        ("https://www.youtube.com/feeds/videos.xml?channel_id=UC123", True),
        ("https://feeds.test/videos.xml", False),
    ],
)
def test_a_youtube_feed_404_is_temporary(url: str, temporary: bool) -> None:
    request = httpx2.Request("GET", url)
    response = httpx2.Response(404, request=request)
    error = httpx2.HTTPStatusError("404", request=request, response=response)

    assert is_temporary(error) is temporary


def test_an_error_response_is_logged_with_what_was_sent_and_received() -> None:
    page = "<html>\n  <body>" + "Not   Found " * 200 + "</body></html>"
    server = FakeServer(
        {
            "/moved.xml": httpx2.Response(301, headers={"Location": f"{BASE}/gone.xml"}),
            "/gone.xml": httpx2.Response(
                404,
                text=page,
                headers={"Content-Type": "text/html", "Server": "ESF", "Set-Cookie": "id=1"},
            ),
        }
    )

    with capture_logs() as logs:
        result = server.fetcher().fetch(
            FeedRequest(f"{BASE}/moved.xml", etag='"v1"', last_modified="Sat, 17 Oct 2026")
        )

    assert result.error is not None
    assert result.error.startswith("HTTPStatusError")
    [entry] = [entry for entry in logs if entry["event"] == "feed failed"]
    assert entry["status_code"] == 404
    assert entry["final_url"] == f"{BASE}/gone.xml"
    assert entry["redirects"] == [f"{BASE}/moved.xml"]
    assert entry["sent"] == {"If-None-Match": '"v1"', "If-Modified-Since": "Sat, 17 Oct 2026"}
    assert entry["headers"]["Server"] == "ESF"
    assert "Set-Cookie" not in entry["headers"]
    assert entry["body"].startswith("Not Found Not Found")
    assert len(entry["body"]) == DIAGNOSTIC_BODY_CHARS


def test_a_failure_without_a_response_logs_no_response_details() -> None:
    server = FakeServer({"/down.xml": httpx2.ConnectError("refused")})

    with capture_logs() as logs:
        server.fetcher().fetch(FeedRequest(f"{BASE}/down.xml"))

    [entry] = [entry for entry in logs if entry["event"] == "feed failed"]
    assert "status_code" not in entry
    assert "body" not in entry


def test_a_url_httpx_refuses_is_a_failure() -> None:
    result = FakeServer().fetcher().fetch(FeedRequest("https://feeds.test/a\x00b"))

    assert result.status is FetchStatus.FAILED
    assert (result.error or "").startswith("InvalidURL")
    assert not result.temporary


def test_a_relative_url_fails_alone_instead_of_stopping_the_others() -> None:
    requests = [FeedRequest("/feed"), FeedRequest(f"{BASE}/rss2.xml")]

    broken, ok = FakeServer().fetcher().fetch_all(requests)

    assert (broken.status, broken.error, broken.temporary) == (
        FetchStatus.FAILED,
        "not an http(s) URL",
        False,
    )
    assert ok.status is FetchStatus.OK


def test_oversized_responses_are_refused() -> None:
    huge = httpx2.Response(200, content=b"<rss>" + b" " * (MAX_BYTES + 1))

    result = fetch("huge", FakeServer({"/huge": huge}))

    assert result.status is FetchStatus.FAILED
    assert "larger than" in (result.error or "")
    assert not result.temporary


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


@pytest.mark.parametrize(
    ("hops", "moved_to"),
    [
        ((301,), f"{BASE}/rss2.xml"),
        ((308, 301), f"{BASE}/rss2.xml"),
        ((302,), None),  # a temporary redirect keeps the URL
        ((301, 307), None),
        ((), None),
    ],
)
def test_a_feed_that_moved_for_good_reports_where_to(
    hops: tuple[int, ...], moved_to: str | None
) -> None:
    paths = [f"/hop{n}" for n in range(len(hops))] + ["/rss2.xml"]
    server = FakeServer(
        {
            path: httpx2.Response(status, headers={"Location": paths[n + 1]})
            for n, (path, status) in enumerate(zip(paths, hops, strict=False))
        }
    )

    result = server.fetcher().fetch(FeedRequest(f"{BASE}{paths[0]}"))

    assert result.status is FetchStatus.OK
    assert result.moved_to == moved_to


VERCEL_CHECKPOINT = (
    "<html><head><style>body{margin:0}</style><title>Vercel Security Checkpoint</title></head>"
    "<body><p>We're verifying your browser</p><p>Website owner? Click here to fix</p>"
    "<noscript>Enable JavaScript to continue</noscript></body></html>"
)


@pytest.mark.parametrize(
    ("response", "temporary"),
    [
        (httpx2.Response(429, text=VERCEL_CHECKPOINT, headers={"Server": "Vercel"}), False),
        (httpx2.Response(503, text="<p>Are you a human?</p>"), False),
        (httpx2.Response(429), True),  # Reddit: an empty refusal may pass with time
        (httpx2.Response(503, text="<p>Down for maintenance</p>"), True),
        (httpx2.Response(503, text="captcha " + "x" * BLOCK_PAGE_MAX_CHARS), True),
    ],
)
def test_an_anti_bot_page_is_a_permanent_failure(
    response: httpx2.Response, temporary: bool
) -> None:
    result = fetch("feed.xml", FakeServer({"/feed.xml": response}))

    assert result.status is FetchStatus.FAILED
    assert result.temporary is temporary
