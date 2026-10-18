"""Embeddings over any OpenAI-compatible `/embeddings` API.

Every vector has `EMBEDDING_DIMENSIONS` components and unit length. Retrieval
models embed a search query differently from the documents it should find, so
each call says which kind of text it embeds; a per-model adapter turns that
into whatever the model expects (a task type, or a prefix on every text).
"""

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Self
from urllib.parse import urlsplit

import openai
from openai.types import CreateEmbeddingResponse

from brzask.clients.retry import APIError, EmptyResponseError, call_with_retries
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.config.settings import Settings
from brzask.db.models import EMBEDDING_DIMENSIONS
from brzask.log import get_logger

log = get_logger(__name__)

EmbeddingKind = Literal["document", "query"]

# Gemini accepts at most 100 texts per request; half of that keeps a request
# well below payload limits with texts of up to 4000 characters.
BATCH_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 60.0


class EmbeddingError(APIError):
    """The embeddings API failed or returned unusable vectors."""


@dataclass(frozen=True, slots=True)
class ModelAdapter:
    """How one model family is told whether it embeds a query or a document."""

    prefixes: dict[EmbeddingKind, str] = field(default_factory=dict)
    request_fields: dict[EmbeddingKind, dict[str, Any]] = field(default_factory=dict)

    def texts(self, texts: Sequence[str], kind: EmbeddingKind) -> list[str]:
        prefix = self.prefixes.get(kind, "")
        return [prefix + text for text in texts]


PLAIN = ModelAdapter()

# Model name fragments, checked in order against the lower-cased model name.
ADAPTERS: tuple[tuple[str, ModelAdapter], ...] = (
    (
        "gemini-embedding",
        ModelAdapter(
            request_fields={
                "query": {"input_type": "search_query"},
                "document": {"input_type": "search_document"},
            }
        ),
    ),
    (
        "nomic-embed",
        ModelAdapter(prefixes={"query": "search_query: ", "document": "search_document: "}),
    ),
    ("e5-", ModelAdapter(prefixes={"query": "query: ", "document": "passage: "})),
)


def adapter_for(model: str) -> ModelAdapter:
    name = model.lower()
    return next((adapter for fragment, adapter in ADAPTERS if fragment in name), PLAIN)


def l2_normalise(vector: Sequence[float]) -> list[float]:
    """Scale to unit length; vectors shortened to fewer dimensions are not unit length."""
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0 or not math.isfinite(norm):
        raise EmbeddingError("the API returned a zero or non-finite vector")
    return [value / norm for value in vector]


class Embedder:
    def __init__(
        self,
        client: openai.OpenAI,
        model: str,
        *,
        openrouter: bool = False,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.model = model  # stored next to every vector as `embedding_model`
        self.adapter = adapter_for(model)
        self.openrouter = openrouter
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Embedding settings, falling back to the LLM's base URL and key."""
        embedding, llm = settings.embedding, settings.llm
        base_url = str(embedding.base_url or llm.base_url)
        secret = embedding.api_key or llm.api_key
        client = openai.OpenAI(
            base_url=base_url,
            # Local servers need no key, but the SDK requires one.
            api_key=secret.get_secret_value() if secret else "unused",
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,  # retried here, with logging and accounting per attempt
        )
        return cls(
            client, embedding.model, openrouter=urlsplit(base_url).hostname == "openrouter.ai"
        )

    def embed(
        self,
        texts: Sequence[str],
        kind: EmbeddingKind,
        *,
        purpose: str = "embedding",
        meter: UsageMeter | None = None,
    ) -> list[list[float]]:
        """One unit-length vector per text, in the same order."""
        if any(not text.strip() for text in texts):
            raise ValueError("cannot embed an empty text")
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[start : start + BATCH_SIZE])
            vectors.extend(self._embed_batch(batch, kind, purpose, meter))
        return vectors

    def _embed_batch(
        self,
        texts: list[str],
        kind: EmbeddingKind,
        purpose: str,
        meter: UsageMeter | None,
    ) -> list[list[float]]:
        def attempt() -> tuple[list[list[float]], CallUsage]:
            started = time.perf_counter()
            response = self._create(texts, kind)
            return _vectors(response, len(texts)), _usage(response, self.model, purpose, started)

        raw, usage = call_with_retries(
            attempt, purpose=purpose, error=EmbeddingError, sleep=self._sleep
        )
        if meter is not None:
            meter.add(usage)
        log.info(
            "embedding call",
            purpose=purpose,
            model=usage.model,
            texts=len(texts),
            input_tokens=usage.input_tokens,
            cost_usd=usage.cost_usd,
            duration_ms=usage.duration_ms,
        )
        return [l2_normalise(vector) for vector in raw]

    def _create(self, texts: list[str], kind: EmbeddingKind) -> CreateEmbeddingResponse:
        extra_body: dict[str, Any] = dict(self.adapter.request_fields.get(kind, {}))
        if self.openrouter:
            # Without require_parameters OpenRouter may route to a provider that
            # ignores `dimensions`; asking for the cost is OpenRouter-only too.
            extra_body["provider"] = {"require_parameters": True}
            extra_body["usage"] = {"include": True}
        return self.client.embeddings.create(
            model=self.model,
            input=self.adapter.texts(texts, kind),
            dimensions=EMBEDDING_DIMENSIONS,
            encoding_format="float",
            extra_body=extra_body or None,
        )


def _vectors(response: CreateEmbeddingResponse, expected: int) -> list[list[float]]:
    # `data` is required by the schema, but some providers send an error object instead.
    data = sorted(response.data or [], key=lambda item: item.index)
    if not data:
        error = (response.model_extra or {}).get("error")
        raise EmptyResponseError(f"no embeddings{f': {error}' if error else ''}")
    if len(data) != expected:
        raise EmbeddingError(f"asked for {expected} embeddings, got {len(data)}")
    vectors = [list(item.embedding) for item in data]
    sizes = {len(vector) for vector in vectors}
    if sizes != {EMBEDDING_DIMENSIONS}:
        raise EmbeddingError(
            f"expected {EMBEDDING_DIMENSIONS} dimensions, got {sorted(sizes)}; "
            "the provider ignored `dimensions`, choose another model or provider"
        )
    return vectors


def _usage(
    response: CreateEmbeddingResponse, model: str, purpose: str, started: float
) -> CallUsage:
    usage = response.usage
    cost = (usage.model_extra or {}).get("cost") if usage else None
    return CallUsage(
        model=response.model or model,
        purpose=purpose,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=0,
        cost_usd=float(cost) if isinstance(cost, int | float) else None,
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
