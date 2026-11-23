from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from brzask.db.models import DeepDiveStatus
from tests.factories import Factories


def test_interrupted_dives_fail_on_start(app: FastAPI, session: Session, make: Factories) -> None:
    article = make.article()
    queued = make.deep_dive(article, focus="a")
    running = make.deep_dive(article, focus="b", status=DeepDiveStatus.RUNNING)
    done = make.deep_dive(article, focus="c", status=DeepDiveStatus.DONE)
    session.commit()

    with TestClient(app):
        pass

    session.expire_all()
    assert [(d.status, d.error) for d in (queued, running)] == [
        (DeepDiveStatus.FAILED, "interrupted"),
        (DeepDiveStatus.FAILED, "interrupted"),
    ]
    assert done.status is DeepDiveStatus.DONE
