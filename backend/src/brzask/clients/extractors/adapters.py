"""The extractors: one class per way of getting an article's text."""

from typing import Any

import httpx2
import trafilatura

from brzask.clients.extractors.base import Extracted, ExtractionError, ExtractionInput
from brzask.clients.http import ResponseTooLargeError, read_limited

# Article pages are rarely above 2 MB of HTML; larger responses are not articles.
MAX_PAGE_BYTES = 5 * 1024 * 1024
PAGE_TIMEOUT = httpx2.Timeout(30.0, connect=10.0)
# Hosted readers render pages in a browser, which takes longer than a plain fetch.
READER_TIMEOUT = httpx2.Timeout(60.0, connect=10.0)
# Feeds often carry only a teaser of a few hundred characters; below this the
# page is likely to have more. A starting point, to be checked with extract-bench.
FEED_MIN_CHARS = 1500


class FeedExtractor:
    """The full content the feed itself carried (content:encoded, Atom content)."""

    name = "feed"
    fetches_page = False

    def extract(self, item: ExtractionInput) -> Extracted | None:
        content = (item.feed_content or "").strip()
        return Extracted(content) if len(content) >= FEED_MIN_CHARS else None


class TrafilaturaExtractor:
    """Fetches the page and extracts the main text locally, as Markdown."""

    name = "trafilatura"
    fetches_page = True

    def __init__(self, client: httpx2.Client) -> None:
        self.client = client

    def extract(self, item: ExtractionInput) -> Extracted | None:
        html = self._download(item.url)
        text = trafilatura.extract(
            html,
            url=item.url,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
        )
        if not text:
            return None
        metadata = trafilatura.extract_metadata(html, default_url=item.url)
        return Extracted(
            text,
            title=metadata.title if metadata else None,
            author=metadata.author if metadata else None,
            published=metadata.date if metadata else None,
        )

    def _download(self, url: str) -> str:
        try:
            with self.client.stream(
                "GET", url, timeout=PAGE_TIMEOUT, headers={"Accept": "text/html,*/*;q=0.5"}
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "")
                if content_type and "html" not in content_type:
                    raise ExtractionError(f"not an HTML page ({content_type.split(';')[0]})")
                body = read_limited(response, MAX_PAGE_BYTES)
                encoding = response.encoding or "utf-8"
        except (httpx2.HTTPError, ResponseTooLargeError) as error:
            raise ExtractionError(f"{type(error).__name__}: {error}") from error
        return body.decode(encoding, errors="replace")


class JinaExtractor:
    """Jina Reader (r.jina.ai): renders the page and returns Markdown. Works without a key."""

    name = "jina"
    fetches_page = True
    endpoint = "https://r.jina.ai/"

    def __init__(self, client: httpx2.Client, api_key: str | None = None) -> None:
        self.client = client
        self.api_key = api_key

    def extract(self, item: ExtractionInput) -> Extracted | None:
        headers = {"Accept": "application/json", "X-Return-Format": "markdown"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = _json(self.client, "GET", self.endpoint + item.url, headers=headers).get("data")
        if not isinstance(data, dict) or not data.get("content"):
            return None
        return Extracted(
            str(data["content"]),
            title=_str(data.get("title")),
            published=_str(data.get("publishedTime")),
        )


class FirecrawlExtractor:
    """Firecrawl's scrape endpoint, hosted or self-hosted."""

    name = "firecrawl"
    fetches_page = True

    def __init__(self, client: httpx2.Client, base_url: str, api_key: str | None = None) -> None:
        self.client = client
        self.url = base_url.rstrip("/") + "/v1/scrape"
        self.api_key = api_key

    def extract(self, item: ExtractionInput) -> Extracted | None:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        body = {"url": item.url, "formats": ["markdown"], "onlyMainContent": True}
        response = _json(self.client, "POST", self.url, headers=headers, json=body)
        data = response.get("data")
        if not response.get("success") or not isinstance(data, dict) or not data.get("markdown"):
            return None
        raw_metadata = data.get("metadata")
        metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
        return Extracted(
            str(data["markdown"]),
            title=_str(metadata.get("title")),
            author=_str(metadata.get("author")),
            published=_str(metadata.get("publishedTime")),
        )


class Crawl4AIExtractor:
    """A Crawl4AI server's Markdown endpoint, with its main-content ("fit") filter."""

    name = "crawl4ai"
    fetches_page = True

    def __init__(self, client: httpx2.Client, base_url: str) -> None:
        self.client = client
        self.url = base_url.rstrip("/") + "/md"

    def extract(self, item: ExtractionInput) -> Extracted | None:
        response = _json(self.client, "POST", self.url, json={"url": item.url, "f": "fit"})
        markdown = response.get("markdown")
        if response.get("success") is False or not isinstance(markdown, str) or not markdown:
            return None
        return Extracted(markdown)


def _json(client: httpx2.Client, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = client.request(method, url, timeout=READER_TIMEOUT, **kwargs)
        response.raise_for_status()
        data = response.json()
    except (httpx2.HTTPError, ValueError) as error:
        raise ExtractionError(f"{type(error).__name__}: {error}") from error
    if not isinstance(data, dict):
        raise ExtractionError("unexpected response")
    return data


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
