import json
from pathlib import Path
from typing import Any

import httpx2
import pytest

from brzask.clients.extractors import ExtractionError, ExtractionInput, unusable_reason
from brzask.clients.extractors.adapters import (
    FEED_MIN_CHARS,
    MAX_PAGE_BYTES,
    Crawl4AIExtractor,
    FeedExtractor,
    FirecrawlExtractor,
    JinaExtractor,
    TrafilaturaExtractor,
)

PAGE = (Path(__file__).parents[2] / "fixtures" / "pages" / "article.html").read_text()
URL = "https://blog.example.com/posts/queue"


class Server:
    def __init__(self, response: httpx2.Response | Exception) -> None:
        self.response = response
        self.requests: list[httpx2.Request] = []
        self.client = httpx2.Client(transport=httpx2.MockTransport(self.handle))

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def body(self) -> Any:
        return json.loads(self.requests[0].content)


def html(text: str = PAGE, content_type: str = "text/html; charset=utf-8") -> httpx2.Response:
    return httpx2.Response(200, text=text, headers={"Content-Type": content_type})


# --- feed ----------------------------------------------------------------------


def test_feed_uses_full_content_only() -> None:
    extractor = FeedExtractor()
    full = "word " * (FEED_MIN_CHARS // 5 + 1)

    assert extractor.extract(ExtractionInput(URL, feed_content=full)) is not None
    assert extractor.extract(ExtractionInput(URL, feed_content="A teaser [...]")) is None
    assert extractor.extract(ExtractionInput(URL, snippet=full)) is None
    assert not extractor.fetches_page


# --- trafilatura ---------------------------------------------------------------


def test_trafilatura_extracts_markdown_and_metadata() -> None:
    server = Server(html())

    extracted = TrafilaturaExtractor(server.client).extract(ExtractionInput(URL))

    assert extracted is not None
    assert "SKIP LOCKED" in extracted.text
    assert "- One fewer service" in extracted.text  # Markdown list
    assert "All rights reserved" not in extracted.text  # footer dropped
    assert "Jobs" not in extracted.text.split("\n")[0]  # navigation dropped
    assert extracted.title == "Why we moved our queue to Postgres"
    assert extracted.author == "Ada Example"
    assert extracted.published == "2026-10-16"
    assert server.requests[0].url == URL


def test_trafilatura_returns_none_for_an_empty_page() -> None:
    server = Server(html("<html><body></body></html>"))

    assert TrafilaturaExtractor(server.client).extract(ExtractionInput(URL)) is None


def test_trafilatura_leaves_judging_short_text_to_the_chain() -> None:
    server = Server(html("<html><body><nav>Home</nav></body></html>"))

    extracted = TrafilaturaExtractor(server.client).extract(ExtractionInput(URL))

    assert extracted is not None
    assert unusable_reason(extracted.text) == "too_short"


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx2.Response(404), "HTTPStatusError"),
        (httpx2.ConnectError("refused"), "ConnectError"),
        (html("%PDF-1.7", "application/pdf"), "not an HTML page (application/pdf)"),
        (html("x" * (MAX_PAGE_BYTES + 1)), "larger than"),
    ],
)
def test_trafilatura_failures(response: httpx2.Response | Exception, error: str) -> None:
    with pytest.raises(ExtractionError, match=error.replace("(", r"\(").replace(")", r"\)")):
        TrafilaturaExtractor(Server(response).client).extract(ExtractionInput(URL))


def test_trafilatura_refuses_a_url_httpx_cannot_send() -> None:
    with pytest.raises(ExtractionError, match="InvalidURL"):
        TrafilaturaExtractor(Server(html()).client).extract(ExtractionInput("https://a\x00b/"))


def test_jina_refuses_a_url_httpx_cannot_send() -> None:
    with pytest.raises(ExtractionError, match="InvalidURL"):
        JinaExtractor(Server(html()).client).extract(ExtractionInput("https://a\x00b/"))


# --- jina ----------------------------------------------------------------------


def test_jina_reads_markdown_with_an_optional_key() -> None:
    server = Server(
        httpx2.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "title": "T",
                    "content": "# T\n\nBody",
                    "publishedTime": "2026-10-16",
                    "usage": {"tokens": 5372},
                },
            },
        )
    )

    extracted = JinaExtractor(server.client, api_key="jina-key").extract(ExtractionInput(URL))

    assert extracted is not None
    assert (extracted.text, extracted.title, extracted.published, extracted.tokens) == (
        "# T\n\nBody",
        "T",
        "2026-10-16",
        5372,
    )
    request = server.requests[0]
    assert str(request.url) == f"https://r.jina.ai/{URL}"
    assert request.headers["Authorization"] == "Bearer jina-key"
    assert request.headers["X-Return-Format"] == "markdown"


def test_jina_without_key_and_without_content() -> None:
    server = Server(httpx2.Response(200, json={"data": {"content": ""}}))

    assert JinaExtractor(server.client).extract(ExtractionInput(URL)) is None
    assert "Authorization" not in server.requests[0].headers


@pytest.mark.parametrize(
    "response",
    [httpx2.Response(429), httpx2.Response(200, text="not json"), httpx2.ReadTimeout("slow")],
)
def test_jina_failures(response: httpx2.Response | Exception) -> None:
    with pytest.raises(ExtractionError):
        JinaExtractor(Server(response).client).extract(ExtractionInput(URL))


# --- firecrawl -----------------------------------------------------------------


def test_firecrawl_scrape() -> None:
    server = Server(
        httpx2.Response(
            200,
            json={
                "success": True,
                "data": {"markdown": "Body", "metadata": {"title": "T", "author": "A"}},
            },
        )
    )

    extracted = FirecrawlExtractor(server.client, "https://fc.test/", "fc-key").extract(
        ExtractionInput(URL)
    )

    assert extracted is not None
    assert (extracted.text, extracted.title, extracted.author) == ("Body", "T", "A")
    assert str(server.requests[0].url) == "https://fc.test/v1/scrape"
    assert server.requests[0].headers["Authorization"] == "Bearer fc-key"
    assert server.body() == {"url": URL, "formats": ["markdown"], "onlyMainContent": True}


def test_firecrawl_unsuccessful_scrape() -> None:
    server = Server(httpx2.Response(200, json={"success": False, "error": "blocked"}))

    assert FirecrawlExtractor(server.client, "http://fc.test").extract(ExtractionInput(URL)) is None
    assert "Authorization" not in server.requests[0].headers


# --- crawl4ai ------------------------------------------------------------------


def test_crawl4ai_markdown_endpoint() -> None:
    server = Server(httpx2.Response(200, json={"url": URL, "markdown": "Body", "success": True}))

    extracted = Crawl4AIExtractor(server.client, "http://crawl4ai:11235").extract(
        ExtractionInput(URL)
    )

    assert extracted is not None
    assert extracted.text == "Body"
    assert str(server.requests[0].url) == "http://crawl4ai:11235/md"
    assert server.body() == {"url": URL, "f": "fit"}
    assert "Authorization" not in server.requests[0].headers


def test_crawl4ai_sends_its_api_token() -> None:
    server = Server(httpx2.Response(200, json={"markdown": "Body", "success": True}))

    Crawl4AIExtractor(server.client, "http://crawl4ai:11235", "token").extract(ExtractionInput(URL))

    assert server.requests[0].headers["Authorization"] == "Bearer token"


def test_crawl4ai_failure() -> None:
    server = Server(httpx2.Response(200, json={"success": False, "markdown": ""}))

    assert (
        Crawl4AIExtractor(server.client, "http://crawl4ai:11235").extract(ExtractionInput(URL))
        is None
    )


def test_trafilatura_detects_a_charset_named_only_in_the_page() -> None:
    text = "Zażółć gęślą jaźń. " * 30
    body = (
        '<html><head><meta charset="windows-1250"><title>T</title></head>'
        f"<body><article><p>{text}</p></article></body></html>"
    ).encode("windows-1250")
    server = Server(httpx2.Response(200, content=body, headers={"Content-Type": "text/html"}))

    extracted = TrafilaturaExtractor(server.client).extract(ExtractionInput(URL))

    assert extracted is not None
    assert "Zażółć gęślą jaźń" in extracted.text


def test_trafilatura_reads_content_types_in_any_case() -> None:
    server = Server(html(content_type="Text/HTML; charset=UTF-8"))

    assert TrafilaturaExtractor(server.client).extract(ExtractionInput(URL)) is not None
