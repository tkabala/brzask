import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from brzask.db.models import Article, DeepDive, DeepDiveStatus, RunKind
from brzask.repositories import DeepDiveRepository
from brzask.repositories.deep_dives import DuplicateDeepDiveError
from tests.factories import Factories

AT = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)


def test_create_refuses_a_duplicate_in_progress(session: Session, make: Factories) -> None:
    article = make.article()
    repository = DeepDiveRepository(session)
    first = repository.create(article.id, "for Proxmox")
    assert (first.status, first.focus) == (DeepDiveStatus.QUEUED, "for Proxmox")

    with pytest.raises(DuplicateDeepDiveError):
        repository.create(article.id, "  FOR proxmox ")

    repository.fail(first.id, "boom", AT)
    again = repository.create(article.id, "for proxmox")
    assert again.id != first.id
    assert repository.create(article.id, "").focus == ""


def test_a_running_dive_counts_as_in_progress(session: Session, make: Factories) -> None:
    article = make.article()
    repository = DeepDiveRepository(session)
    dive = repository.create(article.id, "")
    repository.start(dive.id, make.run(AT, kind=RunKind.DEEP_DIVE).id)
    with pytest.raises(DuplicateDeepDiveError):
        repository.create(article.id, "")


def test_the_same_focus_on_another_article_is_fine(session: Session, make: Factories) -> None:
    repository = DeepDiveRepository(session)
    repository.create(make.article().id, "x")
    repository.create(make.article().id, "x")


def dive_in(
    repository: DeepDiveRepository, article_id: int, status: DeepDiveStatus, read: bool = False
) -> DeepDive:
    dive = repository.create(article_id, f"focus {uuid.uuid4()}")
    if status is DeepDiveStatus.DONE:
        repository.finish(
            dive.id, report={}, sources=[], thin=False, searched_web=True, model="m", at=AT
        )
        if read:
            repository.mark_read(dive.id, AT)
    elif status is DeepDiveStatus.FAILED:
        repository.fail(dive.id, "boom", AT)
    elif status is DeepDiveStatus.RUNNING:
        dive.status = DeepDiveStatus.RUNNING
        repository.session.flush()
    return dive


def test_counts(session: Session, make: Factories) -> None:
    article = make.article()
    repository = DeepDiveRepository(session)
    dive_in(repository, article.id, DeepDiveStatus.DONE)
    dive_in(repository, article.id, DeepDiveStatus.DONE)
    dive_in(repository, article.id, DeepDiveStatus.DONE, read=True)
    dive_in(repository, article.id, DeepDiveStatus.QUEUED)
    dive_in(repository, article.id, DeepDiveStatus.RUNNING)
    dive_in(repository, article.id, DeepDiveStatus.FAILED)

    assert repository.counts() == (2, 2)


def test_finish_stores_the_report(session: Session, make: Factories) -> None:
    repository = DeepDiveRepository(session)
    dive = repository.create(make.article().id, "")
    run = make.run(AT, kind=RunKind.DEEP_DIVE)
    repository.start(dive.id, run.id)
    assert (dive.status, dive.run_id) == (DeepDiveStatus.RUNNING, run.id)

    report = {"background": [{"text": "t", "sources": [1]}], "practice": [], "further": []}
    sources = [{"n": 1, "url": "https://a.example/", "title": "A", "origin": "article"}]
    repository.finish(
        dive.id, report=report, sources=sources, thin=True, searched_web=False, model="m", at=AT
    )

    stored = repository.get(dive.id)
    assert stored is not None
    assert (stored.status, stored.report, stored.sources) == (DeepDiveStatus.DONE, report, sources)
    assert (stored.thin, stored.searched_web, stored.model, stored.finished_at) == (
        True,
        False,
        "m",
        AT,
    )


def test_mark_read_keeps_the_first_time(session: Session, make: Factories) -> None:
    repository = DeepDiveRepository(session)
    dive = dive_in(repository, make.article().id, DeepDiveStatus.DONE)

    assert repository.mark_read(dive.id, AT)
    assert repository.mark_read(dive.id, AT + timedelta(hours=1))
    assert dive.read_at == AT
    assert not repository.mark_read(dive.id + 1000, AT)


def test_fail_interrupted_touches_only_active_ones(session: Session, make: Factories) -> None:
    article = make.article()
    repository = DeepDiveRepository(session)
    queued = dive_in(repository, article.id, DeepDiveStatus.QUEUED)
    running = dive_in(repository, article.id, DeepDiveStatus.RUNNING)
    done = dive_in(repository, article.id, DeepDiveStatus.DONE)
    failed = dive_in(repository, article.id, DeepDiveStatus.FAILED)

    assert repository.fail_interrupted(AT) == 2

    session.expire_all()
    assert [(d.status, d.error) for d in (queued, running)] == [
        (DeepDiveStatus.FAILED, "interrupted"),
        (DeepDiveStatus.FAILED, "interrupted"),
    ]
    assert (done.status, failed.error) == (DeepDiveStatus.DONE, "boom")


def test_page_is_newest_first_and_pages_by_before(session: Session, make: Factories) -> None:
    article = make.article()
    repository = DeepDiveRepository(session)
    dives = [repository.create(article.id, f"f{n}") for n in range(3)]
    for n, dive in enumerate(dives):
        dive.created_at = AT + timedelta(minutes=n)
    session.flush()

    assert [d.id for d in repository.page(2, None)] == [dives[2].id, dives[1].id]
    assert [d.id for d in repository.page(2, dives[1].created_at)] == [dives[0].id]
    assert [d.id for d in repository.for_article(article.id)] == [d.id for d in reversed(dives)]


def test_deleting_the_article_deletes_its_dives(session: Session, make: Factories) -> None:
    article = make.article()
    DeepDiveRepository(session).create(article.id, "")
    session.execute(delete(Article).where(Article.id == article.id))
    assert session.scalars(select(DeepDive)).all() == []
