from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from brzask.db.models import Article, BriefBasis
from brzask.repositories import BriefRepository
from brzask.repositories.briefs import Brief, Chapter
from brzask.services.auth import link_signature
from tests.api.conftest import SECRET, log_in
from tests.factories import Factories

DAY = date(2026, 11, 16)
BRIEF = Brief(
    gist="The gist.",
    points=["one", "two", "three"],
    caveats=["a vendor post"],
    chapters=[Chapter(0, "Intro"), Chapter(754, "Demo")],
)
PROBLEM = "application/problem+json"


def with_brief(
    session: Session, article: Article, basis: BriefBasis = BriefBasis.FULL_TEXT
) -> None:
    BriefRepository(session).save(article.id, BRIEF, basis, "test/model")
    session.commit()


def brief_opened_at(session: Session, article: Article) -> object:
    session.expire_all()
    return session.scalar(select(Article.brief_opened_at).where(Article.id == article.id))


def test_digest_articles_say_whether_they_have_a_brief(
    client: TestClient, make: Factories, session: Session
) -> None:
    briefed = make.article(digest_date=DAY, digest_position=1)
    plain = make.article(digest_date=DAY, digest_position=2)
    with_brief(session, briefed)

    articles = client.get(f"/api/v1/digests/{DAY}").json()["articles"]

    assert [(a["id"], a["has_brief"]) for a in articles] == [(briefed.id, True), (plain.id, False)]
    assert [a["brief_opened_at"] for a in articles] == [None, None]
    single = client.get(f"/api/v1/articles/{briefed.id}").json()
    assert single["has_brief"] is True


@pytest.mark.parametrize("auth_settings", ["password"], indirect=True)
def test_brief_is_returned_with_chapter_links(
    client: TestClient, make: Factories, session: Session
) -> None:
    article = make.article(
        link="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="A talk",
        digest_date=DAY,
    )
    with_brief(session, article, BriefBasis.TRANSCRIPT)
    log_in(client)

    response = client.get(f"/api/v1/articles/{article.id}/brief")

    assert response.status_code == 200
    body = response.json()
    assert body["article"]["id"] == article.id
    assert body["article"]["title"] == "A talk"
    assert body["article"]["has_brief"] is True
    assert (body["gist"], body["points"], body["caveats"], body["basis"]) == (
        "The gist.",
        ["one", "two", "three"],
        ["a vendor post"],
        "transcript",
    )
    demo = body["chapters"][1]
    assert (demo["start"], demo["title"]) == (754, "Demo")
    signature = link_signature(SECRET, article.id, 754)
    assert demo["open_url"] == f"/open?id={article.id}&t=754&sig={signature}"
    assert signature != link_signature(SECRET, article.id)


def test_brief_of_an_article_without_one_is_404(client: TestClient, make: Factories) -> None:
    article = make.article(digest_date=DAY)

    response = client.get(f"/api/v1/articles/{article.id}/brief")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM
    assert client.get("/api/v1/articles/999999/brief").status_code == 404


def test_brief_open_records_the_first_view_only(
    client: TestClient, make: Factories, session: Session
) -> None:
    article = make.article(digest_date=DAY)
    with_brief(session, article)

    first = client.post(f"/api/v1/articles/{article.id}/brief-open")
    seen = brief_opened_at(session, article)
    again = client.post(f"/api/v1/articles/{article.id}/brief-open")

    assert (first.status_code, again.status_code) == (204, 204)
    assert seen is not None
    assert brief_opened_at(session, article) == seen
    shown = client.get(f"/api/v1/articles/{article.id}").json()
    assert shown["brief_opened_at"] is not None


def test_brief_open_without_a_brief_is_404_and_records_nothing(
    client: TestClient, make: Factories, session: Session
) -> None:
    article = make.article(digest_date=DAY)
    session.commit()

    response = client.post(f"/api/v1/articles/{article.id}/brief-open")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM
    assert brief_opened_at(session, article) is None
    assert client.post("/api/v1/articles/999999/brief-open").status_code == 404


@pytest.mark.parametrize("auth_settings", ["password"], indirect=True)
def test_brief_open_needs_a_session(client: TestClient, make: Factories, session: Session) -> None:
    article = make.article(digest_date=DAY)
    with_brief(session, article)
    url = f"/api/v1/articles/{article.id}/brief-open"

    assert client.post(url).status_code == 401
    csrf = log_in(client)
    assert client.post(url).status_code == 403  # a write without the CSRF token
    assert brief_opened_at(session, article) is None
    assert client.post(url, headers={"X-CSRF-Token": csrf}).status_code == 204
    assert brief_opened_at(session, article) is not None


def test_brief_open_works_without_a_login_in_mode_none(
    client: TestClient, make: Factories, session: Session
) -> None:
    article = make.article(digest_date=DAY)
    with_brief(session, article)

    assert client.post(f"/api/v1/articles/{article.id}/brief-open").status_code == 204
