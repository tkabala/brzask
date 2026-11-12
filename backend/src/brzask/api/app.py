"""The HTTP application.

The JSON API lives under `/api/v1`; its OpenAPI document (`/api/v1/openapi.json`)
is the contract the frontend client is generated from. `/open` (links that
record an open), `/feed` (the digest as Atom), probes (`/healthz`, `/readyz`)
and `/metrics` sit at the root: the first two end up in feed readers and
mail, the others where
orchestrators and scrapers expect them. The built web app, when given, takes
every other path.

With BASE_URL, everything is served under its path (e.g. `/brzask/`), and
also without it: proxies that strip the prefix and probes that never knew
it reach the same routes.
"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any

import anyio.to_thread
from fastapi import APIRouter, Depends, FastAPI
from fastapi.openapi.utils import get_openapi
from opentelemetry.metrics import MeterProvider
from prometheus_client import CollectorRegistry
from sqlalchemy.orm import Session, sessionmaker
from starlette.routing import Route

from brzask import __version__
from brzask.api import (
    articles,
    auth,
    digests,
    feed,
    health,
    interests,
    metrics,
    opens,
    problems,
    runs,
    search,
    sources,
    status,
    web,
)
from brzask.api.auth import Auth, require_user
from brzask.api.clients import ApiClients
from brzask.config import get_settings
from brzask.config.settings import AuthSettings, ServerSettings
from brzask.db.models import RunKind
from brzask.log import get_logger
from brzask.mcp.runs import BackgroundRuns
from brzask.mcp.server import McpDeps, McpEndpoint, build_mcp
from brzask.services.open_rate import register_open_rate
from brzask.services.runs import Pipeline, sweep_abandoned
from brzask.telemetry import instrument_app

log = get_logger(__name__)

API_PREFIX = "/api/v1"
OPENAPI_URL = f"{API_PREFIX}/openapi.json"


def create_app(
    sessions: sessionmaker[Session],
    *,
    metrics_registry: CollectorRegistry,
    meter_provider: MeterProvider | None = None,
    clients: ApiClients | None = None,
    auth_settings: AuthSettings | None = None,
    server: ServerSettings | None = None,
    web_dir: Path | None = None,
    pipelines: Mapping[RunKind, Pipeline] | None = None,
) -> FastAPI:
    """`metrics_registry` is what `/metrics` renders; the meter provider (the
    global one unless given) must feed it through a Prometheus reader; `clients`
    reach outside services (embeddings, feed lookup) and `auth_settings` say who
    may use the API; `server` gives BASE_URL; all three come from the settings
    unless given. `web_dir` is the built web app to serve at `/`; without it only
    the API is served. `pipelines` replaces the real ones for runs agents start."""
    server = server or get_settings().server
    clients = clients or ApiClients()
    agent_runs = BackgroundRuns(sessions, pipelines)
    mcp = build_mcp(McpDeps(sessions, clients, agent_runs))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await anyio.to_thread.run_sync(sweep_abandoned, sessions, datetime.now(UTC))
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            await anyio.to_thread.run_sync(agent_runs.close)

    app = FastAPI(
        lifespan=lifespan,
        # The committed document has no servers; the client adds its own base URL.
        root_path_in_servers=False,
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
    app.state.clients = clients
    app.state.auth = Auth(
        auth_settings or get_settings().auth,
        root_path=server.root_path,
        public_url=server.public_url,
    )
    if app.state.auth.mode == "none":
        log.warning(
            "AUTH_MODE=none: NO LOGIN. Anyone who can reach this server can read "
            "and change everything. Use it only on a machine nobody else can reach."
        )
    problems.install(app)

    api = APIRouter(
        prefix=API_PREFIX,
        dependencies=[Depends(require_user)],
        responses=problems.responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN),
    )
    for module in (digests, articles, search, sources, interests, runs, status):
        api.include_router(module.router)
    app.include_router(api)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(opens.router)
    app.include_router(feed.router)
    app.include_router(health.router)
    app.include_router(metrics.router)
    # An exact route: a mount would answer `/mcp` with a redirect to `/mcp/`.
    app.router.routes.append(
        Route(
            "/mcp",
            McpEndpoint(mcp, app.state.auth, sessions),
            methods=["GET", "POST", "DELETE"],
            include_in_schema=False,
        )
    )
    if web_dir is not None:
        # Last, so every route above wins over a file of the same name.
        app.mount("/", web.WebApp(web_dir, f"{server.root_path}/"), name="web")

    app.openapi = lambda: _openapi(app)  # type: ignore[method-assign]
    instrument_app(app, meter_provider)
    if server.root_path:
        # Outside the instrumentation's middleware, which matches the route
        # before any middleware added with add_middleware runs.
        build = app.build_middleware_stack
        app.build_middleware_stack = lambda: web.PathPrefix(  # type: ignore[method-assign]
            build(), root_path=server.root_path
        )
    register_open_rate(
        sessions, meter_provider.get_meter("brzask.digest") if meter_provider else None
    )
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
