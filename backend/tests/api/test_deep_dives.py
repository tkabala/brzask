from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from brzask.api import deep_dives as api
from brzask.api.pagination import encode_cursor
from brzask.config.settings import BudgetSettings
from brzask.db.models import Article, ArticleContent, ContentKind, DeepDiveStatus
from brzask.repositories import DeepDiveRepository
from tests.factories import Factories

PROBLEM = "application/problem+json"
REPORT = {
    "background": [{"text": "Why.", "sources": [1, 2]}],
    "practice": [{"text": "Run it.", "command": "pve8to9", "sources": [3]}],
    "further": [{"source": 3, "why": "Docs."}],
}


class FakeRunner:
    def __init__(self) -> None:
        self.submitted: list[int] = []

    def submit(self, dive_id: int) -> None:
        self.submitted.append(dive_id)

    def close(self, grace: float = 5.0) -> None:
        pass


@pytest.fixture
def runner(app: FastAPI) -> FakeRunner:
    fake = FakeRunner()
    app.state.deep_dives = fake
    return fake


def with_content(session: Session, make: Factories) -> Article:
    article = make.article(title="Proxmox 9", digest_date=date(2026, 11, 22))
    session.add(ArticleContent(article_id=article.id, text="Text.", kind=ContentKind.PAGE))
    session.commit()
    return article


def test_start(client: TestClient, session: Session, make: Factories, runner: FakeRunner) -> None:
    article = with_content(session, make)

    answer = client.post(f"/api/v1/articles/{article.id}/deep-dives", json={"focus": " on ZFS "})

    assert answer.status_code == 202
    body = answer.json()
    assert (body["status"], body["focus"], body["article"]) == (
        "queued",
        "on ZFS",
        {"id": article.id, "title": "Proxmox 9"},
    )
    assert runner.submitted == [body["id"]]
    assert client.post(f"/api/v1/articles/{article.id}/deep-dives", json={}).status_code == 202


def test_refusals(
    client: TestClient, session: Session, make: Factories, runner: FakeRunner
) -> None:
    article = with_content(session, make)
    bare = make.article()
    session.commit()
    url = f"/api/v1/articles/{article.id}/deep-dives"

    assert client.post(url, json={"focus": "x" * 301}).status_code == 422
    assert client.post("/api/v1/articles/999999/deep-dives", json={}).status_code == 404

    no_content = client.post(f"/api/v1/articles/{bare.id}/deep-dives", json={})
    assert (no_content.status_code, no_content.headers["content-type"]) == (409, PROBLEM)
    listed = client.get(f"/api/v1/articles/{bare.id}/deep-dives").json()
    assert (listed["can_start"], listed["reason"]) == (
        False,
        "this article has no stored text to go deeper from",
    )

    assert client.post(url, json={"focus": "a"}).status_code == 202
    duplicate = client.post(url, json={"focus": "A "})
    assert duplicate.status_code == 409
    assert "same focus" in duplicate.json()["detail"]
    assert len(runner.submitted) == 1


def test_budget_reached(
    client: TestClient,
    session: Session,
    make: Factories,
    runner: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article = with_content(session, make)
    make.run(datetime.now(UTC), cost=0.5)
    session.commit()
    monkeypatch.setattr(api, "_limits", lambda: (BudgetSettings(daily_usd=Decimal("0.1")), UTC))

    answer = client.post(f"/api/v1/articles/{article.id}/deep-dives", json={})

    assert answer.status_code == 409
    assert "0.1" in answer.json()["detail"]
    assert DeepDiveRepository(session).for_article(article.id) == []
    assert client.get(f"/api/v1/articles/{article.id}/deep-dives").json()["can_start"] is False


def test_list_and_get(client: TestClient, session: Session, make: Factories) -> None:
    article = with_content(session, make)
    older = make.article(title="Older")
    sources = [
        {
            "n": 1,
            "url": article.link,
            "title": "Proxmox 9",
            "origin": "article",
            "article_id": article.id,
        },
        {"n": 2, "url": older.link, "title": "Older", "origin": "archive", "article_id": older.id},
        {
            "n": 3,
            "url": "https://docs.example/",
            "title": "Docs",
            "origin": "web",
            "article_id": None,
        },
    ]
    done = make.deep_dive(
        article,
        focus="a",
        status=DeepDiveStatus.DONE,
        report=REPORT,
        sources=sources,
        finished_at=datetime.now(UTC),
        searched_web=True,
    )
    make.deep_dive(article, focus="b")
    session.commit()

    listed = client.get("/api/v1/deep-dives").json()
    assert (listed["unread"], listed["active"], len(listed["items"])) == (1, 1, 2)
    first = client.get("/api/v1/deep-dives?limit=1").json()
    assert first["next_cursor"] is not None
    rest = client.get(f"/api/v1/deep-dives?limit=1&cursor={first['next_cursor']}").json()
    assert [first["items"][0]["focus"], rest["items"][0]["focus"]] == ["b", "a"]
    assert rest["next_cursor"] is None
    assert client.get("/api/v1/deep-dives?cursor=nonsense").status_code == 400
    short = encode_cursor([datetime.now(UTC).isoformat()])
    assert client.get(f"/api/v1/deep-dives?cursor={short}").status_code == 400

    body = client.get(f"/api/v1/deep-dives/{done.id}").json()
    assert body["report"] == {
        "background": [{"text": "Why.", "sources": [1, 2]}],
        "practice": [{"text": "Run it.", "command": "pve8to9", "sources": [3]}],
        "further": [{"source": 3, "why": "Docs."}],
    }
    assert [s["open_url"] is not None for s in body["sources"]] == [False, True, False]
    assert body["sources"][1]["open_url"].startswith(f"/open?id={older.id}")
    assert (body["searched_web"], body["thin"], body["article_link"]) == (True, False, article.link)
    assert client.get("/api/v1/deep-dives/999999").status_code == 404
    assert (
        client.get(f"/api/v1/articles/{article.id}/deep-dives").json()["items"][0]["focus"] == "b"
    )


def test_read_keeps_the_first_time(client: TestClient, session: Session, make: Factories) -> None:
    dive = make.deep_dive(make.article(), status=DeepDiveStatus.DONE, report=REPORT)
    session.commit()

    assert client.post(f"/api/v1/deep-dives/{dive.id}/read").status_code == 204
    session.refresh(dive)
    first = dive.read_at
    assert first is not None
    assert client.post(f"/api/v1/deep-dives/{dive.id}/read").status_code == 204
    session.refresh(dive)
    assert dive.read_at == first
    assert client.post("/api/v1/deep-dives/999999/read").status_code == 404


def test_retry(client: TestClient, session: Session, make: Factories, runner: FakeRunner) -> None:
    article = with_content(session, make)
    failed = make.deep_dive(article, focus="on ZFS", status=DeepDiveStatus.FAILED, error="boom")
    done = make.deep_dive(article, focus="x", status=DeepDiveStatus.DONE, report=REPORT)
    session.commit()

    again = client.post(f"/api/v1/deep-dives/{failed.id}/retry")
    assert again.status_code == 202
    assert (again.json()["focus"], again.json()["status"]) == ("on ZFS", "queued")
    assert runner.submitted == [again.json()["id"]]
    assert client.post(f"/api/v1/deep-dives/{done.id}/retry").status_code == 409


def test_markdown(client: TestClient, session: Session, make: Factories) -> None:
    article = make.article(title="Proxmox 9")
    done = make.deep_dive(
        article,
        status=DeepDiveStatus.DONE,
        report=REPORT,
        sources=[{"n": 1, "url": article.link, "title": "Proxmox 9", "origin": "article"}],
        finished_at=datetime(2026, 11, 23, tzinfo=UTC),
    )
    running = make.deep_dive(article, focus="b", status=DeepDiveStatus.RUNNING)
    session.commit()

    answer = client.get(f"/api/v1/deep-dives/{done.id}/markdown")

    assert answer.status_code == 200
    assert answer.headers["content-type"] == "text/markdown; charset=utf-8"
    assert answer.headers["content-disposition"] == (
        'attachment; filename="2026-11-23-proxmox-9.md"'
    )
    assert answer.text.startswith("# Proxmox 9\n")
    assert client.get(f"/api/v1/deep-dives/{running.id}/markdown").status_code == 409


@pytest.mark.parametrize("auth_settings", ["password"], indirect=True)
def test_a_session_is_required(client: TestClient, session: Session, make: Factories) -> None:
    article = make.article()
    session.commit()
    for method, url in [
        ("get", f"/api/v1/articles/{article.id}/deep-dives"),
        ("post", f"/api/v1/articles/{article.id}/deep-dives"),
        ("get", "/api/v1/deep-dives"),
        ("get", "/api/v1/deep-dives/1"),
        ("post", "/api/v1/deep-dives/1/read"),
        ("post", "/api/v1/deep-dives/1/retry"),
        ("get", "/api/v1/deep-dives/1/markdown"),
    ]:
        assert client.request(method, url).status_code == 401, url
