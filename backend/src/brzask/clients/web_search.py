"""Web search for source discovery: SearXNG, Brave, or an online LLM."""

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol, Self

import httpx2
import openai
from openai.types.chat import ChatCompletion

from brzask import prompts
from brzask.clients.http import new_client
from brzask.clients.retry import APIError, call_with_retries
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.config.settings import Settings
from brzask.log import get_logger
from brzask.telemetry import api_call_span
from brzask.text import strip_html

log = get_logger(__name__)

TIMEOUT = httpx2.Timeout(30.0, connect=10.0)
# Online models search and read pages before answering.
LLM_TIMEOUT_SECONDS = 120.0
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"

_URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
_TRAILING = ".,;:!?*_)]>'\""
# Perplexity ends sentences with footnote markers such as "[1]".
_FOOTNOTE = re.compile(r"\[\d+\]")
# `:online` citations carry the whole page text; a search result needs a line.
SNIPPET_CHARS = 300
# Separators models put between title, URL and description: hyphen, en dash, em dash.
_SEPARATORS = " -\u2013\u2014:"


class WebSearchError(APIError):
    """The search service failed; the message says why."""


@dataclass(frozen=True, slots=True)
class SearchResult:
    url: str
    title: str
    snippet: str


class WebSearch(Protocol):
    name: str

    def search(
        self, query: str, *, limit: int = 10, meter: UsageMeter | None = None
    ) -> list[SearchResult]: ...


class SearxngSearch:
    """A SearXNG instance's JSON API (`search.formats` must include `json`)."""

    name = "searxng"

    def __init__(self, client: httpx2.Client, base_url: str) -> None:
        self.client = client
        self.url = base_url.rstrip("/") + "/search"

    def search(
        self, query: str, *, limit: int = 10, meter: UsageMeter | None = None
    ) -> list[SearchResult]:
        data = _get_json(self.client, self.url, params={"q": query, "format": "json"})
        items = data.get("results")
        return _results(
            (_str(item.get("url")), _str(item.get("title")), _str(item.get("content")))
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict)
        )[:limit]


class BraveSearch:
    name = "brave"

    def __init__(self, client: httpx2.Client, api_key: str) -> None:
        self.client = client
        self.api_key = api_key

    def search(
        self, query: str, *, limit: int = 10, meter: UsageMeter | None = None
    ) -> list[SearchResult]:
        data = _get_json(
            self.client,
            BRAVE_URL,
            params={"q": query, "count": min(limit, 20)},
            headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
        )
        web = data.get("web")
        items = web.get("results") if isinstance(web, dict) else None
        return _results(
            (_str(item.get("url")), _str(item.get("title")), _str(item.get("description")))
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict)
        )[:limit]


class LLMOnlineSearch:
    """An LLM with web access (Perplexity Sonar, or any model with OpenRouter's `:online`).

    Results are the pages the answer lists, then the pages it cites; providers
    return citations in different places, and all of them are read.
    """

    name = "llm-online"

    def __init__(
        self,
        client: openai.OpenAI,
        model: str,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.model = model
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        llm = settings.llm
        client = openai.OpenAI(
            base_url=str(llm.base_url),
            api_key=llm.api_key.get_secret_value() if llm.api_key else "unused",
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
        return cls(client, settings.web_search.web_search_model)

    def search(
        self, query: str, *, limit: int = 10, meter: UsageMeter | None = None
    ) -> list[SearchResult]:
        prompt = prompts.render("web_search", query=query, limit=limit)

        def attempt() -> tuple[ChatCompletion, int]:
            started = time.perf_counter()
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                extra_body={"usage": {"include": True}},
            )
            return response, round((time.perf_counter() - started) * 1000)

        with api_call_span("chat", self.model, "web_search") as span:
            response, duration_ms = call_with_retries(
                attempt, purpose="web_search", error=WebSearchError, sleep=self._sleep
            )
            usage = _usage(response, self.model, duration_ms)
            span.record(usage)
        if meter is not None:
            meter.add(usage)
        results = llm_results(response.model_dump())
        log.info("web search", provider=self.name, model=self.model, results=len(results))
        return results[:limit]


def llm_results(response: dict[str, Any]) -> list[SearchResult]:
    """Pages from an online model's answer: listed in the text first, then cited.

    Through OpenRouter, Perplexity and `:online` models alike return citations
    as `message.annotations[].url_citation`; Perplexity's own API puts them in
    top-level `search_results` and `citations`.
    """
    choices = response.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    content = message.get("content") or ""
    found: list[tuple[str, str, str]] = []

    for line in content.splitlines():
        match = _URL.search(line)
        if match:
            url = match.group(0).rstrip(_TRAILING)
            title = re.sub(r"^[\s\-*\d.)#]+", "", line[: match.start()]).replace("*", "")
            title = title.strip(_SEPARATORS + "[]()").strip()  # also `[Title](url)`
            snippet = line[match.end() :].lstrip(_SEPARATORS + ")]").strip()
            found.append((url, title, snippet))

    # OpenRouter: message.annotations[].url_citation {url, title, content}.
    for annotation in message.get("annotations") or []:
        citation = annotation.get("url_citation") if isinstance(annotation, dict) else None
        if isinstance(citation, dict):
            found.append(
                (
                    _str(citation.get("url")),
                    _str(citation.get("title")),
                    _str(citation.get("content")),
                )
            )
    # Perplexity: search_results [{title, url, snippet}] and citations [url].
    for item in response.get("search_results") or []:
        if isinstance(item, dict):
            found.append(
                (_str(item.get("url")), _str(item.get("title")), _str(item.get("snippet")))
            )
    for url in response.get("citations") or []:
        found.append((_str(url), "", ""))
    return _results(found)


def build_web_search(settings: Settings, client: httpx2.Client | None = None) -> WebSearch | None:
    """The configured search, or None when `WEB_SEARCH` is empty."""
    search = settings.web_search
    match search.provider:
        case None:
            return None
        case "searxng":
            assert search.searxng_url is not None  # noqa: S101  (settings validate it)
            return SearxngSearch(client or new_client(TIMEOUT), str(search.searxng_url))
        case "brave":
            assert search.brave_api_key is not None  # noqa: S101  (settings validate it)
            return BraveSearch(
                client or new_client(TIMEOUT), search.brave_api_key.get_secret_value()
            )
        case "llm-online":
            return LLMOnlineSearch.from_settings(settings)


def _results(items: Iterable[tuple[str, str, str]]) -> list[SearchResult]:
    """Results with an http(s) URL, first occurrence of each URL, text cleaned."""
    seen: set[str] = set()
    results: list[SearchResult] = []
    for url, title, snippet in items:
        url = url.strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        snippet = _FOOTNOTE.sub("", strip_html(snippet)).strip()
        if len(snippet) > SNIPPET_CHARS:
            snippet = snippet[:SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"
        results.append(SearchResult(url, strip_html(title), snippet))
    return results


def _get_json(client: httpx2.Client, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = client.get(url, timeout=TIMEOUT, **kwargs)
        response.raise_for_status()
        data = response.json()
    except (httpx2.HTTPError, ValueError) as error:
        raise WebSearchError(f"{type(error).__name__}: {error}") from error
    if not isinstance(data, dict):
        raise WebSearchError("unexpected response")
    return data


def _usage(response: ChatCompletion, model: str, duration_ms: int) -> CallUsage:
    usage = response.usage
    cost = (usage.model_extra or {}).get("cost") if usage else None
    return CallUsage(
        model=response.model or model,
        purpose="web_search",
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        cost_usd=float(cost) if isinstance(cost, int | float) else None,
        duration_ms=duration_ms,
    )


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""
