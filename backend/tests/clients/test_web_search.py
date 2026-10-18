import json
from typing import Any

import httpx2
import openai
import pytest

from brzask.clients.usage import UsageMeter
from brzask.clients.web_search import (
    SNIPPET_CHARS,
    BraveSearch,
    LLMOnlineSearch,
    SearchResult,
    SearxngSearch,
    WebSearchError,
    build_web_search,
    llm_results,
)
from brzask.config.settings import Settings


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


# --- SearXNG -------------------------------------------------------------------


def test_searxng_json_results() -> None:
    server = Server(
        httpx2.Response(
            200,
            json={
                "query": "postgres internals",
                "results": [
                    {"url": "https://a.example/", "title": "A <b>blog</b>", "content": "About A"},
                    {"url": "https://a.example/", "title": "Duplicate", "content": ""},
                    {"url": "ftp://files.example/", "title": "Not web", "content": ""},
                    {"title": "No URL"},
                    {"url": "https://b.example/post", "title": "B", "content": None},
                ],
            },
        )
    )

    results = SearxngSearch(server.client, "http://searxng:8080/").search("postgres internals")

    assert results == [
        SearchResult("https://a.example/", "A blog", "About A"),
        SearchResult("https://b.example/post", "B", ""),
    ]
    request = server.requests[0]
    assert request.url.path == "/search"
    assert request.url.params["q"] == "postgres internals"
    assert request.url.params["format"] == "json"


def test_searxng_limit() -> None:
    items = [{"url": f"https://{i}.example/", "title": str(i)} for i in range(20)]
    server = Server(httpx2.Response(200, json={"results": items}))

    assert len(SearxngSearch(server.client, "http://s").search("q", limit=5)) == 5


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(403, text="json format disabled"),
        httpx2.Response(200, text="<html>not json</html>"),
        httpx2.Response(200, json=["not", "an", "object"]),
        httpx2.ConnectError("refused"),
    ],
)
def test_searxng_failures(response: httpx2.Response | Exception) -> None:
    with pytest.raises(WebSearchError):
        SearxngSearch(Server(response).client, "http://s").search("q")


# --- Brave ---------------------------------------------------------------------


def test_brave_results() -> None:
    server = Server(
        httpx2.Response(
            200,
            json={
                "type": "search",
                "web": {
                    "results": [
                        {
                            "url": "https://a.example/",
                            "title": "A",
                            "description": "Deep dives into <strong>Postgres</strong>",
                        }
                    ]
                },
            },
        )
    )

    results = BraveSearch(server.client, "brave-key").search("postgres", limit=30)

    assert results == [SearchResult("https://a.example/", "A", "Deep dives into Postgres")]
    request = server.requests[0]
    assert request.headers["X-Subscription-Token"] == "brave-key"
    assert request.url.params["count"] == "20"  # the API maximum


def test_brave_without_web_results() -> None:
    server = Server(httpx2.Response(200, json={"type": "search"}))

    assert BraveSearch(server.client, "k").search("q") == []


def test_brave_rate_limit() -> None:
    with pytest.raises(WebSearchError, match="429"):
        BraveSearch(Server(httpx2.Response(429)).client, "k").search("q")


# --- LLM online ----------------------------------------------------------------

# Shapes as returned through OpenRouter (trimmed).
SONAR_CONTENT = """Postgres Pro Blog - https://postgrespro.com/blog - Internals, recent posts.[1]

**Internals for Interns** - https://internals-for-interns.com/tags/postgresql/ - Deep dives.[3][4]

1. [Egor Rogov's Blog](https://postgrespro.com/blog/Rogov) - An ongoing series."""


def completion(
    content: str, *, annotations: list[Any] | None = None, **extra: Any
) -> dict[str, Any]:
    return {
        "id": "gen-1",
        "object": "chat.completion",
        "created": 0,
        "model": "perplexity/sonar",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content, "annotations": annotations},
            }
        ],
        "usage": {
            "prompt_tokens": 40,
            "completion_tokens": 200,
            "total_tokens": 240,
            "cost": 0.00527,
        },
        **extra,
    }


def citation(url: str, title: str = "", content: str | None = None) -> dict[str, Any]:
    cited: dict[str, Any] = {"url": url, "title": title, "start_index": 0, "end_index": 0}
    if content is not None:
        cited["content"] = content
    return {"type": "url_citation", "url_citation": cited}


def test_answer_lines_come_first_then_citations() -> None:
    response = completion(
        SONAR_CONTENT,
        annotations=[
            citation("https://postgrespro.com/blog", "Blog"),
            citation("https://dev.to/series/39304", "PostgreSQL Internals Series"),
        ],
    )

    results = llm_results(response)

    assert results == [
        SearchResult(
            "https://postgrespro.com/blog", "Postgres Pro Blog", "Internals, recent posts."
        ),
        SearchResult(
            "https://internals-for-interns.com/tags/postgresql/",
            "Internals for Interns",
            "Deep dives.",
        ),
        SearchResult(
            "https://postgrespro.com/blog/Rogov", "Egor Rogov's Blog", "An ongoing series."
        ),
        SearchResult("https://dev.to/series/39304", "PostgreSQL Internals Series", ""),
    ]


def test_online_citations_with_page_text_are_shortened() -> None:
    page = "PostgreSQL Storage Internals | boringSQL\n\n" + "word " * 500
    response = completion(
        "No list in this answer.",
        annotations=[citation("https://boringsql.com/guides/storage/", "Storage", page)],
    )

    [result] = llm_results(response)

    assert result.url == "https://boringsql.com/guides/storage/"
    assert len(result.snippet) <= SNIPPET_CHARS + 1
    assert result.snippet.endswith("…")


def test_perplexity_api_citations() -> None:
    response = completion(
        "See the sources.",
        search_results=[{"title": "PG Internals", "url": "https://a.example/", "snippet": "S"}],
        citations=["https://a.example/", "https://b.example/"],
    )

    assert llm_results(response) == [
        SearchResult("https://a.example/", "PG Internals", "S"),
        SearchResult("https://b.example/", "", ""),
    ]


def test_an_answer_without_choices() -> None:
    assert llm_results({"error": {"message": "upstream"}}) == []


class FakeLLM:
    def __init__(self, *responses: httpx2.Response) -> None:
        self.responses = list(responses)
        self.bodies: list[dict[str, Any]] = []
        self.sleeps: list[float] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.bodies.append(json.loads(request.content))
        return self.responses.pop(0)

    def search(self, *, report_cost: bool = True) -> LLMOnlineSearch:
        client = openai.OpenAI(
            base_url="https://llm.test/v1",
            api_key="k",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self.handle)),
        )
        return LLMOnlineSearch(
            client, "perplexity/sonar", report_cost=report_cost, sleep=self.sleeps.append
        )


def test_llm_online_search_asks_the_online_model_and_meters_the_call() -> None:
    fake = FakeLLM(httpx2.Response(200, json=completion(SONAR_CONTENT)))
    meter = UsageMeter()

    results = fake.search().search("PostgreSQL internals blogs", limit=2, meter=meter)

    assert [r.url for r in results] == [
        "https://postgrespro.com/blog",
        "https://internals-for-interns.com/tags/postgresql/",
    ]
    [body] = fake.bodies
    assert body["model"] == "perplexity/sonar"
    assert "Search the web for: PostgreSQL internals blogs" in body["messages"][0]["content"]
    assert "up to 2" in body["messages"][0]["content"]
    assert body["usage"] == {"include": True}
    [call] = meter.calls
    assert (call.purpose, call.cost_usd) == ("web_search", 0.00527)


def test_llm_online_asks_for_the_cost_only_where_supported() -> None:
    fake = FakeLLM(httpx2.Response(200, json=completion(SONAR_CONTENT)))

    fake.search(report_cost=False).search("q")

    [body] = fake.bodies
    assert "usage" not in body


def test_list_markers_are_dropped_but_titles_starting_with_digits_kept() -> None:
    content = (
        "1. 37signals blog - https://dev.37signals.com/ - Posts.\n"
        "- 2025 in review - https://example.com/2025 - Recap."
    )

    assert [r.title for r in llm_results(completion(content))] == [
        "37signals blog",
        "2025 in review",
    ]


def test_llm_online_retries_and_fails_as_a_search_error() -> None:
    fake = FakeLLM(
        httpx2.Response(503, json={"error": {"message": "busy"}}),
        httpx2.Response(400, json={"error": {"message": "bad model"}}),
    )

    with pytest.raises(WebSearchError, match="bad model"):
        fake.search().search("q")

    assert len(fake.sleeps) == 1


# --- Settings ------------------------------------------------------------------


def test_no_search_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_SEARCH", raising=False)

    assert build_web_search(Settings()) is None


@pytest.mark.parametrize(
    ("env", "kind"),
    [
        ({"WEB_SEARCH": "searxng", "SEARXNG_URL": "http://searxng:8080"}, SearxngSearch),
        ({"WEB_SEARCH": "brave", "BRAVE_API_KEY": "k"}, BraveSearch),
        ({"WEB_SEARCH": "llm-online", "WEB_SEARCH_MODEL": "x/y:online"}, LLMOnlineSearch),
    ],
)
def test_build_web_search(env: dict[str, str], kind: type, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    search = build_web_search(Settings())

    assert isinstance(search, kind)
    if isinstance(search, LLMOnlineSearch):
        assert search.model == "x/y:online"
