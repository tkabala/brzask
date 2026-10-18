import json
import math
from typing import Any

import httpx2
import openai
import pytest

from brzask.clients.embeddings import (
    BATCH_SIZE,
    PLAIN,
    Embedder,
    EmbeddingError,
    adapter_for,
    l2_normalise,
)
from brzask.clients.retry import ATTEMPTS
from brzask.clients.usage import UsageMeter
from brzask.config.settings import Settings
from brzask.db.models import EMBEDDING_DIMENSIONS

DIMENSIONS = EMBEDDING_DIMENSIONS


def vector(seed: float, size: int = DIMENSIONS) -> list[float]:
    """A vector that is not unit length, as Gemini returns when shortened."""
    return [seed + i / size for i in range(size)]


class FakeAPI:
    """An embeddings API that answers each input with `vector(position)` and records requests."""

    def __init__(
        self,
        *failures: httpx2.Response | Exception,
        size: int = DIMENSIONS,
        cost: float | None = None,
        reverse: bool = False,
    ) -> None:
        self.failures = list(failures)
        self.size = size
        self.cost = cost
        self.reverse = reverse
        self.requests: list[dict[str, Any]] = []
        self.sleeps: list[float] = []
        self.client = openai.OpenAI(
            base_url="https://embeddings.test/v1",
            api_key="key",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self._handle)),
        )

    def embedder(self, model: str = "test/model", *, openrouter: bool = False) -> Embedder:
        return Embedder(self.client, model, openrouter=openrouter, sleep=self.sleeps.append)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        if self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return failure
        data = [
            {"object": "embedding", "index": i, "embedding": vector(float(i + 1), self.size)}
            for i in range(len(body["input"]))
        ]
        if self.reverse:
            data.reverse()
        usage: dict[str, Any] = {"prompt_tokens": 7 * len(data), "total_tokens": 7 * len(data)}
        if self.cost is not None:
            usage["cost"] = self.cost
        return httpx2.Response(
            200, json={"object": "list", "model": body["model"], "data": data, "usage": usage}
        )


def norm(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


# --- Adapters ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "query", "document"),
    [
        ("nomic-embed-text", "search_query: q", "search_document: q"),
        ("nomic-ai/nomic-embed-text-v1.5", "search_query: q", "search_document: q"),
        ("intfloat/multilingual-e5-large", "query: q", "passage: q"),
        ("text-embedding-3-small", "q", "q"),
    ],
)
def test_prefixes_per_model(model: str, query: str, document: str) -> None:
    adapter = adapter_for(model)

    assert adapter.texts(["q"], "query") == [query]
    assert adapter.texts(["q"], "document") == [document]


def test_gemini_is_sent_without_a_task_type() -> None:
    # Stored vectors and the duplicate thresholds come from untyped Gemini vectors.
    assert adapter_for("google/gemini-embedding-001") is PLAIN


def test_unknown_models_are_sent_unchanged() -> None:
    assert adapter_for("mistral-embed") is PLAIN


def test_requests_carry_prefix_dimensions_and_kind() -> None:
    api = FakeAPI()

    api.embedder("nomic-embed-text").embed(["What is new in Postgres?"], "query")
    api.embedder("google/gemini-embedding-001").embed(["An article"], "document")

    nomic, gemini = api.requests
    assert nomic["input"] == ["search_query: What is new in Postgres?"]
    assert nomic["dimensions"] == DIMENSIONS
    assert nomic["encoding_format"] == "float"
    assert "input_type" not in nomic
    assert gemini["input"] == ["An article"]
    assert "input_type" not in gemini


def test_openrouter_requires_the_parameters_and_reports_cost() -> None:
    api = FakeAPI(cost=0.00001)
    meter = UsageMeter()

    api.embedder(openrouter=True).embed(["a"], "document", purpose="dedup", meter=meter)

    [request] = api.requests
    assert request["provider"] == {"require_parameters": True}
    assert request["usage"] == {"include": True}
    [call] = meter.calls
    assert (call.purpose, call.input_tokens, call.output_tokens, call.cost_usd) == (
        "dedup",
        7,
        0,
        0.00001,
    )


def test_other_apis_get_no_openrouter_fields() -> None:
    api = FakeAPI()

    api.embedder().embed(["a"], "document")

    assert "provider" not in api.requests[0]
    assert "usage" not in api.requests[0]


# --- Vectors -------------------------------------------------------------------


def test_vectors_are_unit_length_and_in_input_order() -> None:
    api = FakeAPI(reverse=True)

    first, second = api.embedder().embed(["a", "b"], "document")

    assert norm(first) == pytest.approx(1.0)
    assert norm(second) == pytest.approx(1.0)
    assert first == pytest.approx(l2_normalise(vector(1.0)))
    assert second == pytest.approx(l2_normalise(vector(2.0)))


def test_l2_normalise() -> None:
    assert l2_normalise([3.0, 4.0]) == pytest.approx([0.6, 0.8])
    with pytest.raises(EmbeddingError, match="zero"):
        l2_normalise([0.0, 0.0])
    with pytest.raises(EmbeddingError):
        l2_normalise([math.inf, 1.0])


@pytest.mark.parametrize("size", [3072, 1536, 767])
def test_another_size_fails_loudly(size: int) -> None:
    api = FakeAPI(size=size)

    with pytest.raises(EmbeddingError, match=f"expected {DIMENSIONS} dimensions, got \\[{size}\\]"):
        api.embedder().embed(["a"], "document")


def test_a_missing_vector_fails() -> None:
    short = httpx2.Response(
        200,
        json={
            "object": "list",
            "model": "m",
            "data": [{"object": "embedding", "index": 0, "embedding": vector(1.0)}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        },
    )
    api = FakeAPI(short)

    with pytest.raises(EmbeddingError, match="asked for 2 embeddings, got 1"):
        api.embedder().embed(["a", "b"], "document")


def test_empty_texts_are_rejected_before_any_request() -> None:
    api = FakeAPI()

    with pytest.raises(ValueError, match="empty"):
        api.embedder().embed(["a", "  "], "document")

    assert api.requests == []


def test_nothing_to_embed() -> None:
    api = FakeAPI()

    assert api.embedder().embed([], "query") == []
    assert api.requests == []


# --- Batching and retries ------------------------------------------------------


def test_texts_are_sent_in_batches() -> None:
    api = FakeAPI()
    meter = UsageMeter()
    texts = [f"text {i}" for i in range(2 * BATCH_SIZE + 3)]

    vectors = api.embedder().embed(texts, "document", meter=meter)

    assert [len(request["input"]) for request in api.requests] == [BATCH_SIZE, BATCH_SIZE, 3]
    assert [text for request in api.requests for text in request["input"]] == texts
    assert len(vectors) == len(texts)
    assert vectors[BATCH_SIZE] == pytest.approx(l2_normalise(vector(1.0)))  # first of batch 2
    assert len(meter.calls) == 3


@pytest.mark.parametrize(
    "failure",
    [
        httpx2.Response(503, json={"error": {"message": "busy"}}),
        httpx2.Response(429, json={"error": {"message": "slow down"}}),
        httpx2.Response(200, json={"error": {"message": "upstream failed"}}),
        httpx2.ConnectError("refused"),
    ],
    ids=["503", "429", "error-body", "connect"],
)
def test_temporary_failures_are_retried(failure: httpx2.Response | Exception) -> None:
    api = FakeAPI(failure)

    [result] = api.embedder().embed(["a"], "document")

    assert len(result) == DIMENSIONS
    assert len(api.requests) == 2
    assert len(api.sleeps) == 1


def test_gives_up_after_the_last_attempt() -> None:
    api = FakeAPI(*[httpx2.Response(502, json={}) for _ in range(ATTEMPTS)])

    with pytest.raises(EmbeddingError, match="gave up"):
        api.embedder().embed(["a"], "document")


def test_bad_requests_are_not_retried() -> None:
    api = FakeAPI(httpx2.Response(400, json={"error": {"message": "unknown model"}}))

    with pytest.raises(EmbeddingError, match="unknown model"):
        api.embedder().embed(["a"], "document")

    assert len(api.requests) == 1


# --- Settings ------------------------------------------------------------------


def test_from_settings_falls_back_to_the_llm_url_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-llm")

    embedder = Embedder.from_settings(Settings())

    assert embedder.model == "google/gemini-embedding-001"
    assert str(embedder.client.base_url) == "https://openrouter.ai/api/v1/"
    assert embedder.client.api_key == "sk-llm"
    assert embedder.openrouter


def test_from_settings_with_its_own_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-llm")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("EMBEDDING_API_KEY", "local")

    embedder = Embedder.from_settings(Settings())

    assert str(embedder.client.base_url) == "http://localhost:11434/v1/"
    assert embedder.client.api_key == "local"
    assert not embedder.openrouter
    assert embedder.adapter == adapter_for("nomic-embed-text")
