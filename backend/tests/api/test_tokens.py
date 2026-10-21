"""API tokens: scopes enforced on every route, and recorded as the actor."""

from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from brzask.config.settings import AuthSettings
from brzask.db.models import ApiToken, Change, TokenScope
from brzask.services.tokens import create_token, revoke_token
from tests.factories import Factories


@pytest.fixture
def auth_settings(password_auth: AuthSettings) -> AuthSettings:
    return password_auth


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, follow_redirects=False)


def bearer(session: Session, scope: TokenScope, name: str | None = None) -> dict[str, str]:
    _, value = create_token(session, name or f"{scope.value} script", scope, actor="user")
    session.commit()
    return {"Authorization": f"Bearer {value}"}


def test_read_token_reads_but_cannot_change(
    client: TestClient, session: Session, make: Factories
) -> None:
    source = make.source()
    headers = bearer(session, TokenScope.READ)

    assert client.get("/api/v1/status", headers=headers).status_code == 200
    assert client.get("/api/v1/sources", headers=headers).status_code == 200
    for method, url, body in [
        ("PATCH", f"/api/v1/sources/{source.id}", {"name": "x"}),
        ("POST", "/api/v1/interests", {"topic": "x"}),
        ("PUT", "/api/v1/pause", {"until": "2099-01-01T00:00:00Z"}),
        ("DELETE", "/api/v1/pause", None),
    ]:
        response = client.request(method, url, json=body, headers=headers)
        assert response.status_code == 403, (method, url)
        assert response.json()["detail"] == "This token may only read."


def test_write_token_changes_without_csrf_and_is_the_actor(
    client: TestClient, session: Session, make: Factories
) -> None:
    source = make.source("Old")
    headers = bearer(session, TokenScope.WRITE, "agent")

    response = client.patch(f"/api/v1/sources/{source.id}", json={"name": "New"}, headers=headers)

    assert response.status_code == 200
    change = session.scalars(select(Change).where(Change.action == "source.rename")).one()
    assert change.actor == "token:agent"


def test_unknown_malformed_or_revoked_tokens(client: TestClient, session: Session) -> None:
    headers = bearer(session, TokenScope.WRITE, "old")
    revoke_token(session, "old", datetime.now(UTC), actor="user")
    session.commit()

    for authorization in [
        headers["Authorization"],
        "Bearer brz_made-up",
        "Bearer ",
        "Basic dXNlcjpwYXNz",
    ]:
        response = client.get("/api/v1/status", headers={"Authorization": authorization})
        assert response.status_code == 401, authorization


def test_a_wrong_token_is_not_saved_by_a_session(client: TestClient) -> None:
    from tests.api.conftest import PASSWORD

    https = TestClient(client.app, base_url="https://testserver")
    https.post("/api/v1/auth/login", json={"password": PASSWORD})

    assert https.get("/api/v1/status").status_code == 200
    response = https.get("/api/v1/status", headers={"Authorization": "Bearer brz_wrong"})
    assert response.status_code == 401


def test_last_use_is_recorded(client: TestClient, session: Session) -> None:
    headers = bearer(session, TokenScope.READ, "cron")

    client.get("/api/v1/status", headers=headers)

    session.expire_all()
    token = session.scalars(select(ApiToken).where(ApiToken.name == "cron")).one()
    assert token.last_used_at is not None


def test_tokens_open_links_and_tell_the_session(
    client: TestClient, session: Session, make: Factories
) -> None:
    article = make.article(link="https://news.example/a", digest_date=date(2026, 10, 21))
    headers = bearer(session, TokenScope.READ, "reader")

    assert client.get(f"/open?id={article.id}", headers=headers).status_code == 302
    state = client.get("/api/v1/auth/session", headers=headers).json()
    assert (state["authenticated"], state["csrf_token"]) == (True, None)


def test_tokens_work_behind_an_authenticating_proxy(app: FastAPI, session: Session) -> None:
    app.state.auth.settings = AuthSettings.model_validate(
        {"mode": "header", "session_secret": "s" * 32, "TRUSTED_PROXIES": "10.0.0.0/24"}
    )
    headers = bearer(session, TokenScope.READ)

    # From outside the proxy, as a script on another machine would call.
    stranger = TestClient(app, client=("203.0.113.9", 41000))
    assert stranger.get("/api/v1/status", headers=headers).status_code == 200
    assert stranger.get("/api/v1/status").status_code == 401
