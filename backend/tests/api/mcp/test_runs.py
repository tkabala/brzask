import threading
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import nullcontext
from datetime import UTC, datetime

import anyio
import pytest
from fastapi import FastAPI
from opentelemetry.sdk.metrics import MeterProvider
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from brzask.api.app import create_app
from brzask.api.clients import ApiClients
from brzask.api.metrics import prometheus_reader
from brzask.config.settings import AuthSettings, ServerSettings
from brzask.db.migrations import migrate
from brzask.db.models import RunKind, RunStatus, TokenScope
from brzask.db.session import create_db_engine, session_factory
from brzask.mcp.runs import BackgroundRuns
from brzask.repositories import RunRepository
from brzask.services.runs import Pipeline, RunContext
from brzask.services.tokens import create_token
from tests.api.mcp.conftest import Connect, data, error_text
from tests.factories import Factories

pytestmark = pytest.mark.anyio

release = threading.Event()


def quick(context: RunContext) -> None:
    context.stats["dry_run"] = context.dry_run


def blocking(context: RunContext) -> None:
    release.wait(30)


@pytest.fixture
def own_engine(empty_database_url: str) -> Iterator[Engine]:
    """A database of its own: runs use their own connections from threads."""
    migrate(empty_database_url)
    engine = create_db_engine(empty_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def sessions(own_engine: Engine) -> sessionmaker[Session]:
    return session_factory(own_engine)


@pytest.fixture
def session(sessions: sessionmaker[Session]) -> Iterator[Session]:
    with sessions() as session:
        yield session


@pytest.fixture
def read_token(sessions: sessionmaker[Session]) -> str:
    with sessions.begin() as session:
        return create_token(session, "reader", TokenScope.READ, actor="test")[1]


@pytest.fixture
def write_token(sessions: sessionmaker[Session]) -> str:
    with sessions.begin() as session:
        return create_token(session, "claude", TokenScope.WRITE, actor="test")[1]


@pytest.fixture
def propose_token(sessions: sessionmaker[Session]) -> str:
    with sessions.begin() as session:
        return create_token(session, "helper", TokenScope.PROPOSE, actor="test")[1]


@pytest.fixture
def pipelines() -> dict[RunKind, Pipeline]:
    release.clear()
    return {RunKind.DIGEST: quick, RunKind.REVIEW: blocking}


def fake_replay(days: int, exclude: Sequence[int]) -> Pipeline:
    def pipeline(context: RunContext) -> None:
        if days == 13:
            release.wait(30)
        context.stats.update({"days": days, "excluded": list(exclude)})

    return pipeline


@pytest.fixture
def app(
    sessions: sessionmaker[Session],
    auth_settings: AuthSettings,
    pipelines: dict[RunKind, Pipeline],
) -> FastAPI:
    reader, registry = prometheus_reader()
    return create_app(
        sessions,
        metrics_registry=registry,
        meter_provider=MeterProvider(metric_readers=[reader]),
        clients=ApiClients(feed_finder=lambda: nullcontext(None)),  # type: ignore[arg-type]
        auth_settings=auth_settings,
        server=ServerSettings(),
        pipelines=pipelines,
        replay=fake_replay,
    )


async def until(condition: Callable[[], bool], seconds: float = 5) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        await anyio.sleep(0.05)


def status_of(sessions: sessionmaker[Session], run_id: str) -> RunStatus | None:
    with sessions() as session:
        run = RunRepository(session).get(uuid.UUID(run_id))
        return run.status if run else None


async def test_a_dry_run_with_a_read_token(
    connect: Connect, read_token: str, sessions: sessionmaker[Session]
) -> None:
    async with connect(read_token) as client:
        started = data(await client.call_tool("start_run", {"kind": "digest"}))
        assert (started["kind"], started["dry_run"]) == ("digest", True)
        await until(lambda: status_of(sessions, started["run_id"]) is RunStatus.OK)
        run = data(await client.call_tool("get_run", {"run_id": started["run_id"]}))

    assert run["external"]["stats"]["dry_run"] is True


async def test_a_real_or_forced_run_needs_a_write_token(
    connect: Connect, read_token: str, write_token: str, sessions: sessionmaker[Session]
) -> None:
    async with connect(read_token) as client:
        real = await client.call_tool("start_run", {"kind": "digest", "dry_run": False})
        forced = await client.call_tool("start_run", {"kind": "digest", "force": True})
    async with connect(write_token) as client:
        started = data(await client.call_tool("start_run", {"kind": "digest", "dry_run": False}))

    assert "this needs a write token" in error_text(real)
    assert "this needs a write token" in error_text(forced)
    await until(lambda: status_of(sessions, started["run_id"]) is RunStatus.OK)
    with sessions() as session:
        assert [r.dry_run for r in RunRepository(session).recent(5)] == [False]


async def test_a_propose_token_starts_only_dry_runs(
    connect: Connect, propose_token: str, sessions: sessionmaker[Session]
) -> None:
    async with connect(propose_token) as client:
        real = await client.call_tool("start_run", {"kind": "digest", "dry_run": False})
        started = data(await client.call_tool("start_run", {"kind": "digest"}))

    assert "this needs a write token" in error_text(real)
    await until(lambda: status_of(sessions, started["run_id"]) is RunStatus.OK)


async def test_a_second_run_of_the_same_kind_is_skipped(
    connect: Connect, write_token: str, sessions: sessionmaker[Session]
) -> None:
    async with connect(write_token) as client:
        first = data(await client.call_tool("start_run", {"kind": "review"}))
        second = data(await client.call_tool("start_run", {"kind": "review"}))
        await until(lambda: status_of(sessions, second["run_id"]) is RunStatus.SKIPPED)
        release.set()
        await until(lambda: status_of(sessions, first["run_id"]) is RunStatus.OK)


def test_a_stuck_run_neither_holds_up_closing_nor_the_process_exit(
    sessions: sessionmaker[Session], pipelines: dict[RunKind, Pipeline]
) -> None:
    runs = BackgroundRuns(sessions, pipelines)
    runs.start(RunKind.REVIEW, dry_run=True, force=False)

    began = time.monotonic()
    runs.close(grace=0.2)

    assert time.monotonic() - began < 2
    # Non-daemon threads would be joined at interpreter exit, so a long run
    # would keep a stopping API alive until it was killed.
    agent_threads = [t for t in threading.enumerate() if t.name.startswith("agent-run")]
    assert agent_threads
    assert all(t.daemon for t in agent_threads)
    release.set()


def test_runs_beyond_the_limit_wait_their_turn(
    sessions: sessionmaker[Session], pipelines: dict[RunKind, Pipeline]
) -> None:
    runs = BackgroundRuns(sessions, pipelines, max_workers=1)
    first = runs.start(RunKind.REVIEW, dry_run=True, force=False)
    second = runs.start(RunKind.DIGEST, dry_run=True, force=False)

    assert status_of(sessions, str(first)) is RunStatus.RUNNING
    assert status_of(sessions, str(second)) is None
    release.set()
    deadline = time.monotonic() + 5
    while status_of(sessions, str(second)) is not RunStatus.OK:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    runs.close()


async def test_the_api_closes_runs_left_running_at_start(
    app: FastAPI, sessions: sessionmaker[Session], session: Session
) -> None:
    orphan = uuid.uuid4()
    RunRepository(session).start(orphan, RunKind.DIGEST, datetime(2026, 11, 12, 7, tzinfo=UTC))
    session.commit()

    async with app.router.lifespan_context(app):
        pass

    assert status_of(sessions, str(orphan)) is RunStatus.FAILED


@pytest.mark.parametrize("scope", ["read", "propose", "write"])
async def test_any_agent_token_may_start_a_replay(
    connect: Connect,
    sessions: sessionmaker[Session],
    session: Session,
    make: Factories,
    scope: str,
) -> None:
    source = make.source("Quiet")
    session.commit()
    with sessions.begin() as s:
        token = create_token(s, "agent", TokenScope(scope), actor="test")[1]

    async with connect(token) as client:
        started = data(await client.call_tool("start_replay", {"exclude_source_ids": [source.id]}))
        assert (started["kind"], started["dry_run"]) == ("replay", True)
        await until(lambda: status_of(sessions, started["run_id"]) is RunStatus.OK)
        run = data(await client.call_tool("get_run", {"run_id": started["run_id"]}))

    assert run["kind"] == "replay"
    assert run["external"]["stats"] == {"days": 14, "excluded": [source.id]}


async def test_a_replay_over_the_budget_is_refused(
    connect: Connect,
    read_token: str,
    sessions: sessionmaker[Session],
    session: Session,
    make: Factories,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BUDGET_DAILY_USD", "0.05")
    make.run(datetime.now(UTC), cost=0.06)
    session.commit()

    async with connect(read_token) as client:
        result = await client.call_tool("start_replay", {})

    assert "daily" in error_text(result)
    with sessions() as s:
        assert [r.kind for r in RunRepository(s).recent(5)] == [RunKind.DIGEST]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"exclude_source_ids": [999]}, "no source 999"),
        ({"exclude_source_ids": list(range(1, 52))}, "at most 50 sources"),
        ({"days": 0}, "days"),
        ({"days": 31}, "days"),
    ],
)
async def test_a_replay_with_bad_arguments_is_refused(
    connect: Connect,
    read_token: str,
    sessions: sessionmaker[Session],
    arguments: dict[str, object],
    message: str,
) -> None:
    async with connect(read_token) as client:
        result = await client.call_tool("start_replay", arguments)

    assert message in error_text(result)
    with sessions() as s:
        assert RunRepository(s).recent(5) == []


async def test_a_second_replay_while_one_runs_is_skipped(
    connect: Connect, read_token: str, sessions: sessionmaker[Session]
) -> None:
    async with connect(read_token) as client:
        first = data(await client.call_tool("start_replay", {"days": 13}))
        second = data(await client.call_tool("start_replay", {"days": 13}))
        await until(lambda: status_of(sessions, second["run_id"]) is RunStatus.SKIPPED)
        release.set()
        await until(lambda: status_of(sessions, first["run_id"]) is RunStatus.OK)
        run = data(await client.call_tool("get_run", {"run_id": second["run_id"]}))

    assert run["external"]["stats"]["reason"] == "another replay run is in progress"


async def test_start_run_cannot_start_a_replay(connect: Connect, write_token: str) -> None:
    async with connect(write_token) as client:
        result = await client.call_tool("start_run", {"kind": "replay"})

    assert result.is_error
