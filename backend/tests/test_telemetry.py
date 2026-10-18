import json
from collections.abc import Iterator
from typing import Any

import httpx2
import openai
import pytest
import sentry_sdk
from opentelemetry import metrics, trace
from opentelemetry.instrumentation.httpx import HTTPX2ClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer

from brzask import telemetry
from brzask.clients.embeddings import Embedder
from brzask.clients.llm import LLMClient, LLMError
from brzask.config.settings import TelemetrySettings
from brzask.db.models import EMBEDDING_DIMENSIONS
from brzask.db.session import create_db_engine

# The global tracer provider can be set once per process; every test shares it.
_EXPORTER = InMemorySpanExporter()
_PROVIDER = TracerProvider()
_PROVIDER.add_span_processor(SimpleSpanProcessor(_EXPORTER))
trace.set_tracer_provider(_PROVIDER)


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    _EXPORTER.clear()
    yield _EXPORTER
    _EXPORTER.clear()


def openai_client(*responses: httpx2.Response) -> openai.OpenAI:
    queue = list(responses)
    return openai.OpenAI(
        base_url="https://llm.test/v1",
        api_key="k",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(lambda _: queue.pop(0))),
    )


def chat(content: str = "ok") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "1",
            "object": "chat.completion",
            "created": 0,
            "model": "test/model-2026",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
                "cost": 0.0004,
            },
        },
    )


def only(exporter: InMemorySpanExporter) -> ReadableSpan:
    [span] = exporter.get_finished_spans()
    return span


def test_llm_call_span_has_model_tokens_and_cost(spans: InMemorySpanExporter) -> None:
    LLMClient(openai_client(chat()), "test/model").complete("p", purpose="ranking")

    span = only(spans)
    assert span.name == "chat test/model"
    assert span.kind is trace.SpanKind.CLIENT
    attributes: dict[str, Any] = dict(span.attributes or {})
    assert attributes == {
        "gen_ai.operation.name": "chat",
        "gen_ai.request.model": "test/model",
        "gen_ai.response.model": "test/model-2026",
        "gen_ai.usage.input_tokens": 120,
        "gen_ai.usage.output_tokens": 30,
        "brzask.purpose": "ranking",
        "brzask.cost_usd": 0.0004,
    }
    assert span.status.status_code is StatusCode.UNSET


def test_one_span_covers_the_retries(spans: InMemorySpanExporter) -> None:
    client = openai_client(httpx2.Response(503, json={}), chat())

    LLMClient(client, "test/model", sleep=lambda _: None).complete("p", purpose="ranking")

    assert len(spans.get_finished_spans()) == 1


def test_a_failed_call_marks_the_span(spans: InMemorySpanExporter) -> None:
    client = openai_client(httpx2.Response(400, json={"error": {"message": "bad request"}}))

    with pytest.raises(LLMError):
        LLMClient(client, "test/model").complete("p", purpose="selection")

    span = only(spans)
    assert span.status.status_code is StatusCode.ERROR
    assert [event.name for event in span.events] == ["exception"]
    assert "gen_ai.usage.input_tokens" not in (span.attributes or {})


def test_embedding_call_span(spans: InMemorySpanExporter) -> None:
    body = {
        "object": "list",
        "model": "test/embed",
        "data": [{"object": "embedding", "index": 0, "embedding": [1.0] * EMBEDDING_DIMENSIONS}],
        "usage": {"prompt_tokens": 9, "total_tokens": 9},
    }
    client = openai_client(httpx2.Response(200, content=json.dumps(body)))

    Embedder(client, "test/embed").embed(["text"], "document", purpose="dedup")

    attributes = dict(only(spans).attributes or {})
    assert attributes["gen_ai.operation.name"] == "embeddings"
    assert attributes["gen_ai.usage.input_tokens"] == 9
    assert attributes["gen_ai.usage.output_tokens"] == 0
    assert attributes["brzask.purpose"] == "dedup"
    assert "brzask.cost_usd" not in attributes  # the provider reported none


# --- setup_telemetry -----------------------------------------------------------


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Replace everything with global effects by recorders."""
    recorded: dict[str, list[Any]] = {
        "tracer": [],
        "meter": [],
        "httpx2": [],
        "sql": [],
        "sentry": [],
    }
    monkeypatch.setattr(trace, "set_tracer_provider", recorded["tracer"].append)
    monkeypatch.setattr(metrics, "set_meter_provider", recorded["meter"].append)
    monkeypatch.setattr(
        HTTPX2ClientInstrumentor, "instrument", lambda self: recorded["httpx2"].append(1)
    )
    monkeypatch.setattr(
        SQLAlchemyInstrumentor, "instrument", lambda self, **kw: recorded["sql"].append(kw)
    )
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: recorded["sentry"].append(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *args: None)
    return recorded


def test_nothing_is_set_up_by_default(calls: dict[str, list[Any]]) -> None:
    telemetry.setup_telemetry(TelemetrySettings(), component="cli")

    assert all(not recorded for recorded in calls.values())


def test_an_otlp_endpoint_turns_on_traces_metrics_and_instrumentation(
    calls: dict[str, list[Any]],
) -> None:
    settings = TelemetrySettings.model_validate(
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318/", "OTEL_SERVICE_NAME": "brzask-dev"}
    )

    telemetry.setup_telemetry(settings, component="worker")

    [provider] = calls["tracer"]
    resource = dict(provider.resource.attributes)
    assert resource["service.name"] == "brzask-dev"
    assert resource["brzask.component"] == "worker"
    assert len(calls["meter"]) == 1
    assert calls["httpx2"] == [1]
    assert calls["sql"] == [{"skip_dep_check": True}]
    assert calls["sentry"] == []


def test_a_sentry_dsn_turns_on_error_reports_only(calls: dict[str, list[Any]]) -> None:
    settings = TelemetrySettings.model_validate(
        {"SENTRY_DSN": "https://key@sentry.example/1", "SENTRY_ENVIRONMENT": "staging"}
    )

    telemetry.setup_telemetry(settings, component="api")

    [options] = calls["sentry"]
    assert options["dsn"] == "https://key@sentry.example/1"
    assert options["environment"] == "staging"
    assert options["send_default_pii"] is False
    assert options["release"].startswith("brzask@")
    assert calls["tracer"] == []


def test_sql_queries_produce_spans(
    spans: InMemorySpanExporter, postgres: PostgresContainer
) -> None:
    instrumentor = SQLAlchemyInstrumentor()
    telemetry.instrument_sqlalchemy()
    try:
        engine = create_db_engine(postgres.get_connection_url())
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
    finally:
        instrumentor.uninstrument()

    statements = [
        dict(span.attributes or {}).get("db.statement") for span in spans.get_finished_spans()
    ]
    assert "SELECT 1" in statements
