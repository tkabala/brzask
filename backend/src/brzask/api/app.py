"""The HTTP application.

The JSON API lives under `/api/v1`; its OpenAPI document (`/api/v1/openapi.json`)
is the contract the frontend client is generated from. `/open` (links that
record an open), probes (`/healthz`, `/readyz`) and `/metrics` sit at the
root: the first ends up in feed readers and mail, the others where
orchestrators and scrapers expect them.
"""

from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi
from opentelemetry.metrics import MeterProvider
from prometheus_client import CollectorRegistry
from sqlalchemy.orm import Session, sessionmaker

from brzask import __version__
from brzask.api import (
    articles,
    digests,
    health,
    interests,
    metrics,
    opens,
    problems,
    runs,
    search,
    sources,
    status,
)
from brzask.api.clients import ApiClients
from brzask.telemetry import instrument_app

API_PREFIX = "/api/v1"
OPENAPI_URL = f"{API_PREFIX}/openapi.json"


def create_app(
    sessions: sessionmaker[Session],
    *,
    metrics_registry: CollectorRegistry,
    meter_provider: MeterProvider | None = None,
    clients: ApiClients | None = None,
) -> FastAPI:
    """`metrics_registry` is what `/metrics` renders; the meter provider (the
    global one unless given) must feed it through a Prometheus reader; `clients`
    reach outside services (embeddings, feed lookup), built from the settings
    unless given."""
    app = FastAPI(
        title="brzask",
        version=__version__,
        summary="Self-hosted daily news digest.",
        openapi_url=OPENAPI_URL,
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        # Operation IDs are the route function names, e.g. list_sources, so the
        # generated client reads naturally.
        generate_unique_id_function=lambda route: route.name,
    )
    app.state.sessions = sessions
    app.state.metrics_registry = metrics_registry
    app.state.clients = clients or ApiClients()
    problems.install(app)

    api = APIRouter(prefix=API_PREFIX)
    for module in (digests, articles, search, sources, interests, runs, status):
        api.include_router(module.router)
    app.include_router(api)
    app.include_router(opens.router)
    app.include_router(health.router)
    app.include_router(metrics.router)

    app.openapi = lambda: _openapi(app)  # type: ignore[method-assign]
    instrument_app(app, meter_provider)
    return app


def _openapi(app: FastAPI) -> dict[str, Any]:
    """The OpenAPI document, with validation errors described as problems."""
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version, summary=app.summary, routes=app.routes
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    problem = problems.Problem.model_json_schema(ref_template="#/components/schemas/{model}")
    components.update(problem.pop("$defs", {}))
    components["Problem"] = problem
    components.pop("HTTPValidationError", None)
    components.pop("ValidationError", None)
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            if "422" in operation.get("responses", {}):
                operation["responses"]["422"] = {
                    "description": HTTPStatus.UNPROCESSABLE_CONTENT.phrase,
                    "content": {
                        problems.MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}
                    },
                }
    app.openapi_schema = schema
    return schema
