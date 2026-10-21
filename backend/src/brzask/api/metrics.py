"""`/metrics` in the Prometheus text format.

The metrics come from OpenTelemetry: a Prometheus reader on the meter
provider collects them into a registry, and this route renders it. So
request durations and everything else instrumented show up here without an
OTLP collector.
"""

from fastapi import APIRouter, Request, Response
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest

router = APIRouter()


def prometheus_reader() -> tuple[PrometheusMetricReader, CollectorRegistry]:
    """A reader for the meter provider and the registry `/metrics` renders."""
    registry = CollectorRegistry(auto_describe=True)
    return PrometheusMetricReader(registry=registry), registry


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    registry: CollectorRegistry = request.app.state.metrics_registry
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
