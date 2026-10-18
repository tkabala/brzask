"""Traces, metrics and error reports.

Everything is off by default. `OTEL_EXPORTER_OTLP_ENDPOINT` turns on traces and
metrics over OTLP/HTTP, with spans for outgoing HTTP requests, SQL queries and
every LLM and embedding call; `SENTRY_DSN` turns on error reports. Without
them, the OpenTelemetry API calls in the code are no-ops.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import sentry_sdk
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPX2ClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span

from brzask import __version__
from brzask.clients.usage import CallUsage
from brzask.config.settings import TelemetrySettings
from brzask.log import get_logger

log = get_logger(__name__)

tracer = trace.get_tracer("brzask")


def setup_telemetry(settings: TelemetrySettings, *, component: str) -> None:
    """Configure what the settings turn on; `component` is e.g. "api", "worker" or "cli"."""
    if settings.sentry_dsn is not None:
        sentry_sdk.init(
            dsn=settings.sentry_dsn.get_secret_value(),
            environment=settings.sentry_environment,
            release=f"brzask@{__version__}",
            send_default_pii=False,
            traces_sample_rate=0,  # traces go to OpenTelemetry
        )
        sentry_sdk.set_tag("component", component)
        log.info("sentry enabled", environment=settings.sentry_environment)

    if settings.otlp_endpoint is None:
        return
    endpoint = str(settings.otlp_endpoint).rstrip("/")
    resource = Resource.create(
        {
            SERVICE_NAME: settings.service_name,
            SERVICE_VERSION: __version__,
            "brzask.component": component,
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(tracer_provider)
    reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"))
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))

    HTTPX2ClientInstrumentor().instrument()
    instrument_sqlalchemy()
    log.info("telemetry enabled", endpoint=endpoint, service=settings.service_name)


def instrument_sqlalchemy() -> None:
    """Trace SQL queries of engines created from now on.

    The instrumentation declares support only below SQLAlchemy 2.1 and would
    silently do nothing; it relies on engine events that 2.1 still has, and
    tests check that queries produce spans.
    """
    SQLAlchemyInstrumentor().instrument(skip_dep_check=True)


class CallSpan:
    """Handle on the span of one API call, to attach what the call used."""

    def __init__(self, span: Span) -> None:
        self.span = span

    def record(self, usage: CallUsage) -> None:
        self.span.set_attribute("gen_ai.response.model", usage.model)
        self.span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens)
        self.span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens)
        if usage.cost_usd is not None:
            self.span.set_attribute("brzask.cost_usd", usage.cost_usd)


@contextmanager
def api_call_span(operation: str, model: str, purpose: str) -> Iterator[CallSpan]:
    """A span around one LLM or embedding call, retries included.

    Attribute names follow the OpenTelemetry GenAI conventions where they exist;
    an exception is recorded on the span, which is marked as failed.
    """
    with tracer.start_as_current_span(
        f"{operation} {model}",
        kind=trace.SpanKind.CLIENT,
        attributes={
            "gen_ai.operation.name": operation,
            "gen_ai.request.model": model,
            "brzask.purpose": purpose,
        },
    ) as span:
        yield CallSpan(span)
