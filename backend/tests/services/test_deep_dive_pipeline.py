import threading
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from brzask import prompts
from brzask.clients.llm import LLMError
from brzask.clients.web_search import SearchResult, WebSearchError
from brzask.config.settings import BudgetSettings
from brzask.db.models import (
    ArticleContent,
    ContentKind,
    DeepDiveStatus,
    RunKind,
    RunStatus,
)
from brzask.repositories import DeepDiveRepository, RunRepository
from brzask.services.deep_dive.pipeline import DeepDiveClients, build_deep_dive
from brzask.services.deep_dive.runner import DeepDiveRunner
from brzask.services.notify import deep_dive_ready_message, message_after_run
from brzask.services.runs import RunContext, run_pipeline
from tests.factories import Factories
from tests.services.deep_dive_fakes import FakeSearch
from tests.services.digest.fakes import FakeEmbedder, FakeExtractor
from tests.services.test_briefs import FakeLLM

PLAN = {"background": ["proxmox 9"], "practice": ["pve8to9"], "archive": ["proxmox"]}


def report(_prompt: str, n: int) -> Any:
    if n == 1:
        return PLAN
    return {
        "background": [{"text": "Why.", "sources": [1, 2]}],
        "practice": [],
        "further": [{"source": 2, "why": "Docs."}],
    }


def clients(**fields: Any) -> DeepDiveClients:
    values: dict[str, Any] = {
        "llm": FakeLLM(report),
        "model": "test/model",
        "embedder": FakeEmbedder(),
        "extractor": FakeExtractor({"https://docs.example/": "The docs."}),
        "search": FakeSearch(
            {"proxmox 9": [SearchResult("https://docs.example/", "Docs", "s")], "pve8to9": []}
        ),
        "language": prompts.language("en"),
        "budget": None,
        "timezone": UTC,
    }
    values.update(fields)
    return DeepDiveClients(**values)


def queued(session: Session, make: Factories, focus: str = "") -> int:
    article = make.article(title="Proxmox 9", digest_date=date(2026, 11, 22))
    session.add(ArticleContent(article_id=article.id, text="Text.", kind=ContentKind.PAGE))
    dive = DeepDiveRepository(session).create(article.id, focus)
    session.commit()
    return dive.id


def run(sessions: sessionmaker[Session], dive_id: int, deep: DeepDiveClients) -> Any:
    def pipeline(context: RunContext) -> None:
        build_deep_dive(context, deep, dive_id)

    return run_pipeline(
        sessions, RunKind.DEEP_DIVE, pipelines={RunKind.DEEP_DIVE: pipeline}, notifier=None
    )


def test_a_dive_is_written(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    dive_id = queued(session, make)

    finished = run(sessions, dive_id, clients())

    dive = DeepDiveRepository(session).get(dive_id)
    session.refresh(dive)
    assert dive is not None
    assert (dive.status, dive.run_id, dive.model) == (
        DeepDiveStatus.DONE,
        finished.id,
        "test/model",
    )
    assert dive.report is not None and dive.report["further"] == [{"source": 2, "why": "Docs."}]
    assert [(s["n"], s["origin"]) for s in dive.sources] == [(1, "article"), (2, "web")]
    assert (dive.thin, dive.searched_web) == (False, True)
    assert finished.status is RunStatus.OK
    assert set(finished.stats["deep_dive"]) >= {
        "dive_id",
        "queries",
        "archive_sources",
        "web_results",
        "web_pages_read",
        "sources",
        "thin",
    }


def test_no_web_search_configured(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    dive_id = queued(session, make)
    run(sessions, dive_id, clients(search=None))
    dive = DeepDiveRepository(session).get(dive_id)
    session.refresh(dive)
    assert dive is not None
    assert (dive.status, dive.searched_web, dive.thin) == (DeepDiveStatus.DONE, False, True)


def test_every_search_failing_still_writes(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    dive_id = queued(session, make)
    failing = FakeSearch({"proxmox 9": WebSearchError("down"), "pve8to9": WebSearchError("down")})
    run(sessions, dive_id, clients(search=failing))
    dive = DeepDiveRepository(session).get(dive_id)
    session.refresh(dive)
    assert dive is not None
    assert (dive.status, dive.searched_web, dive.thin) == (DeepDiveStatus.DONE, False, True)


def test_write_failure_fails_the_dive(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    dive_id = queued(session, make)
    llm = FakeLLM(lambda p, n: PLAN if n == 1 else LLMError("provider down"))

    with pytest.raises(LLMError):
        run(sessions, dive_id, clients(llm=llm))

    dive = DeepDiveRepository(session).get(dive_id)
    session.refresh(dive)
    assert dive is not None
    assert dive.status is DeepDiveStatus.FAILED
    assert dive.error == "LLMError: provider down"
    failed = RunRepository(session).latest(RunKind.DEEP_DIVE)
    assert failed is not None and failed.status is RunStatus.FAILED


def test_budget_reached_fails_with_the_reason(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    make.run(datetime.now(UTC), cost=0.5)
    dive_id = queued(session, make)

    finished = run(sessions, dive_id, clients(budget=BudgetSettings(daily_usd=Decimal("0.1"))))

    dive = DeepDiveRepository(session).get(dive_id)
    session.refresh(dive)
    assert dive is not None
    assert finished.status is RunStatus.SKIPPED
    assert dive.status is DeepDiveStatus.FAILED
    assert dive.error is not None and "0.1" in dive.error


def test_ready_notification_links_to_the_dive(session: Session, make: Factories) -> None:
    dive = make.deep_dive(make.article(title="Proxmox 9"), status=DeepDiveStatus.DONE)
    finished = make.run(
        datetime.now(UTC), kind=RunKind.DEEP_DIVE, stats={"deep_dive": {"dive_id": dive.id}}
    )

    message = message_after_run(session, finished, "https://brzask.example/")

    assert message is not None
    assert message.title == "Deep dive ready: Proxmox 9"
    assert f"https://brzask.example/deep-dives/{dive.id}" in message.body
    assert message_after_run(session, finished, None) is None
    assert deep_dive_ready_message("T", None, 1) is None


def test_no_notification_when_failed(session: Session, make: Factories) -> None:
    failed = make.run(
        datetime.now(UTC), kind=RunKind.DEEP_DIVE, status=RunStatus.FAILED, error="boom"
    )
    assert message_after_run(session, failed, "https://brzask.example/") is None


# --- runner ------------------------------------------------------------------------


def test_dives_run_one_at_a_time_in_order(sessions: sessionmaker[Session]) -> None:
    events: list[str] = []
    lock = threading.Lock()
    done = threading.Event()

    def pipeline(dive_id: int) -> Any:
        def build(context: RunContext) -> None:
            with lock:
                events.append(f"start {dive_id}")
            time.sleep(0.05)
            with lock:
                events.append(f"end {dive_id}")
            if dive_id == 3:
                done.set()
            if dive_id == 1:
                raise RuntimeError("the first one fails")

        return build

    runner = DeepDiveRunner(sessions, pipeline, notifier=None)
    for dive_id in (1, 2, 3):
        runner.submit(dive_id)
    assert done.wait(10)
    runner.close()

    assert events == ["start 1", "end 1", "start 2", "end 2", "start 3", "end 3"]


def test_a_skipped_run_fails_its_queued_dive(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    from brzask.services.runs import SkipRunError

    dive_id = queued(session, make)
    finished = threading.Event()

    def pipeline(_dive_id: int) -> Any:
        def build(context: RunContext) -> None:
            finished.set()
            raise SkipRunError("another deep_dive run is in progress")

        return build

    runner = DeepDiveRunner(sessions, pipeline, notifier=None)
    runner.submit(dive_id)
    assert finished.wait(10)
    runner.close(grace=10)

    dive = DeepDiveRepository(session).get(dive_id)
    session.refresh(dive)
    assert dive is not None
    assert (dive.status, dive.error) == (
        DeepDiveStatus.FAILED,
        "another deep_dive run is in progress",
    )
