import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from brzask.db.models import MessageStatus
from brzask.repositories import ConversationRepository
from tests.factories import Factories
from tests.services.conversation_fakes import NOW, VALID


def test_answers_in_progress_settle_on_start(
    app: FastAPI, session: Session, make: Factories
) -> None:
    repository = ConversationRepository(session)
    writing = repository.add_question(repository.get_or_create(make.article().id).id, "Q?", NOW)[1]
    other = repository.get_or_create(make.article().id)
    searching = repository.add_question(other.id, "Q?", NOW)[1]
    repository.finish(
        searching.id, answer=VALID, model="m", usage={}, searched=False, note=None, at=NOW
    )
    repository.begin(searching.id, MessageStatus.SEARCHING)
    session.commit()

    with TestClient(app):
        pass

    session.expire_all()
    assert (writing.status, writing.error) == (MessageStatus.FAILED, "interrupted")
    assert (searching.status, searching.note) == (MessageStatus.DONE, "interrupted")


def test_a_database_error_does_not_stop_the_start(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(self: ConversationRepository, at: object) -> int:
        raise OperationalError("SELECT 1", {}, Exception("the database is not up"))

    monkeypatch.setattr(ConversationRepository, "settle_interrupted", down)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
