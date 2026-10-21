from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from brzask.db.models import Article
from tests.factories import Factories


def opened_at(session: Session, article: Article) -> object:
    session.expire_all()
    return session.scalar(select(Article.opened_at).where(Article.id == article.id))


@pytest.fixture
def no_redirects(client: TestClient) -> TestClient:
    client.follow_redirects = False
    return client


def test_first_open_redirects_and_records(
    no_redirects: TestClient, make: Factories, session: Session
) -> None:
    article = make.article(link="https://news.example/story", digest_date=date(2026, 10, 21))
    session.commit()

    response = no_redirects.get("/open", params={"id": article.id})

    assert response.status_code == 302
    assert response.headers["location"] == "https://news.example/story"
    assert response.headers["cache-control"] == "no-store"
    assert opened_at(session, article) is not None


def test_repeated_opens_keep_the_first(
    no_redirects: TestClient, make: Factories, session: Session
) -> None:
    article = make.article(link="https://news.example/story")
    session.commit()

    no_redirects.get("/open", params={"id": article.id})
    first = opened_at(session, article)
    response = no_redirects.get("/open", params={"id": article.id})

    assert response.status_code == 302
    assert response.headers["location"] == "https://news.example/story"
    assert opened_at(session, article) == first


def test_head_redirects_without_recording(
    no_redirects: TestClient, make: Factories, session: Session
) -> None:
    article = make.article(link="https://news.example/story")
    session.commit()

    response = no_redirects.head("/open", params={"id": article.id})

    assert response.status_code == 302
    assert response.headers["location"] == "https://news.example/story"
    assert opened_at(session, article) is None


def test_unknown_or_missing_id(no_redirects: TestClient) -> None:
    assert no_redirects.get("/open", params={"id": 999999}).status_code == 404
    assert no_redirects.get("/open").status_code == 422
    assert no_redirects.get("/open", params={"id": "x"}).status_code == 422


def test_never_redirects_to_a_non_web_link(
    no_redirects: TestClient, make: Factories, session: Session
) -> None:
    article = make.article(link="javascript:alert(1)")
    session.commit()

    response = no_redirects.get("/open", params={"id": article.id})

    assert response.status_code == 400
    assert "location" not in response.headers
    assert opened_at(session, article) is None


def test_articles_carry_their_open_url(client: TestClient, make: Factories) -> None:
    article = make.article(digest_date=date(2026, 10, 21))

    body = client.get("/api/v1/digests/2026-10-21").json()

    assert body["articles"][0]["open_url"] == f"/open?id={article.id}"
