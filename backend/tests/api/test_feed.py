"""`/feed`: the digest as Atom, opened with a feed token in its URL."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import feedparser
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from brzask.config.settings import AuthSettings
from brzask.db.models import ApiToken, Article, TokenScope
from brzask.services.tokens import create_token, revoke_token
from tests.factories import Factories

DAY = date(2026, 11, 4)


@pytest.fixture
def auth_settings(password_auth: AuthSettings) -> AuthSettings:
    return password_auth


@pytest.fixture
def client(client: TestClient) -> TestClient:
    client.follow_redirects = False
    return client


def token(session: Session, scope: TokenScope = TokenScope.FEED, name: str = "reader") -> str:
    _, value = create_token(session, name, scope, actor="user")
    session.commit()
    return value


def read(client: TestClient, value: str | None, **headers: str) -> Any:
    params = {"token": value} if value is not None else {}
    response = client.get("/feed", params=params, headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/atom+xml; charset=utf-8"
    parsed = feedparser.parse(response.content)
    assert parsed.bozo == 0, parsed.get("bozo_exception")
    return parsed


def test_feed_lists_recent_digests_with_signed_open_links(
    client: TestClient, session: Session, make: Factories
) -> None:
    older = make.article(digest_date=DAY - timedelta(days=1), title="Yesterday")
    first = make.article(
        make.source("Simon Willison"),
        digest_date=DAY,
        title="Original",
        digest_title="Today's first",
        link="https://news.example/first",
        summary="What happened.",
        why_it_matters="Why it matters.",
        topic="LLM news",
    )
    second = make.article(digest_date=DAY, title="Today's second")
    value = token(session)

    parsed = read(client, value)

    ids = [e.id for e in parsed.entries]
    assert ids == [f"urn:brzask:article:{a.id}" for a in (first, second, older)]
    item = parsed.entries[0]
    assert item.title == "Today's first"
    assert item.tags[0].term == "LLM news"
    assert item.author == "Simon Willison"
    assert "Why it matters." in item.content[0].value
    for entry in parsed.entries:
        assert entry.link.startswith("http://testserver/open?id=")
        assert "&sig=" in entry.link
    assert value not in str(parsed)

    url = urlsplit(item.link)
    opened = client.get(f"{url.path}?{url.query}")  # a reader sends no session
    assert opened.status_code == 302
    assert opened.headers["location"] == "https://news.example/first"
    session.expire_all()
    assert session.scalar(select(Article.opened_at).where(Article.id == first.id)) is not None


def test_feed_keeps_seven_days(client: TestClient, session: Session, make: Factories) -> None:
    for back in range(8):
        make.article(digest_date=DAY - timedelta(days=back))
    value = token(session)

    parsed = read(client, value)

    assert len(parsed.entries) == 7


def test_empty_feed_is_valid(client: TestClient, session: Session) -> None:
    parsed = read(client, token(session))

    assert parsed.entries == []
    assert parsed.feed.title == "brzask"


@pytest.mark.parametrize("kind", ["missing", "garbage", "read", "write", "revoked"])
def test_feed_needs_a_feed_token(client: TestClient, session: Session, kind: str) -> None:
    value: str | None
    match kind:
        case "missing":
            value = None
        case "garbage":
            value = "brz_nope"
        case "read":
            value = token(session, TokenScope.READ, "script")
        case "write":
            value = token(session, TokenScope.WRITE, "agent")
        case _:
            value = token(session)
            revoke_token(session, "reader", datetime.now(UTC), actor="user")
            session.commit()

    response = client.get("/feed", params={"token": value} if value else {})

    assert response.status_code == 401
    assert "--scope feed" in response.json()["detail"]


def test_feed_token_records_its_use(client: TestClient, session: Session) -> None:
    read(client, token(session))

    session.expire_all()
    assert session.scalars(select(ApiToken.last_used_at)).one() is not None


@pytest.mark.parametrize("auth_settings", [AuthSettings(mode="none")])
def test_feed_needs_no_token_without_login(
    client: TestClient, session: Session, make: Factories
) -> None:
    make.article(digest_date=DAY)
    session.commit()

    parsed = read(client, None)

    [entry] = parsed.entries
    assert entry.link.startswith("http://testserver/open?id=")
    assert "sig=" not in entry.link


def test_unchanged_feed_answers_304(client: TestClient, session: Session, make: Factories) -> None:
    make.article(digest_date=DAY)
    value = token(session)

    first = client.get("/feed", params={"token": value})
    etag = first.headers["etag"]
    assert first.headers["cache-control"] == "private, no-cache"

    again = client.get("/feed", params={"token": value}, headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag
    weak = client.get("/feed", params={"token": value}, headers={"If-None-Match": f"W/{etag}"})
    assert weak.status_code == 304

    make.article(digest_date=DAY)
    session.commit()
    changed = client.get("/feed", params={"token": value}, headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.headers["etag"] != etag
