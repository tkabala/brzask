"""AUTH_MODE=header: the user name from a reverse proxy, believed only from TRUSTED_PROXIES."""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from brzask.config.settings import AuthSettings
from brzask.services.auth import header_csrf_token, link_signature
from tests.api.conftest import SECRET
from tests.factories import Factories

PROXY = ("10.0.0.5", 41000)
STRANGER = ("203.0.113.9", 41000)
USER = {"Remote-User": "alice"}


@pytest.fixture
def auth_settings() -> AuthSettings:
    return AuthSettings.model_validate(
        {"mode": "header", "session_secret": SECRET, "TRUSTED_PROXIES": "10.0.0.0/24"}
    )


def from_(app: FastAPI, address: tuple[str, int]) -> TestClient:
    return TestClient(app, client=address, follow_redirects=False)


def test_trusted_proxy_with_a_user(app: FastAPI) -> None:
    proxy = from_(app, PROXY)

    assert proxy.get("/api/v1/status", headers=USER).status_code == 200
    state = proxy.get("/api/v1/auth/session", headers=USER).json()
    assert (state["mode"], state["authenticated"], state["user"]) == ("header", True, "alice")
    assert state["csrf_token"] == header_csrf_token(SECRET, "alice")


def test_untrusted_source_is_refused_even_with_the_header(app: FastAPI) -> None:
    stranger = from_(app, STRANGER)

    response = stranger.get("/api/v1/status", headers=USER)

    assert response.status_code == 401
    assert "trusted proxy" in response.json()["detail"]
    assert stranger.get("/api/v1/auth/session", headers=USER).json()["authenticated"] is False


def test_forwarded_for_does_not_make_a_source_trusted(app: FastAPI) -> None:
    stranger = from_(app, STRANGER)

    response = stranger.get("/api/v1/status", headers={**USER, "X-Forwarded-For": "10.0.0.5"})

    assert response.status_code == 401


def test_trusted_proxy_without_a_user(app: FastAPI) -> None:
    proxy = from_(app, PROXY)

    assert proxy.get("/api/v1/status").status_code == 401
    assert proxy.get("/api/v1/status", headers={"Remote-User": "  "}).status_code == 401


def test_changes_need_the_users_csrf_token(app: FastAPI, make: Factories) -> None:
    source = make.source()
    proxy = from_(app, PROXY)
    url = f"/api/v1/sources/{source.id}"
    csrf = header_csrf_token(SECRET, "alice")
    bobs = header_csrf_token(SECRET, "bob")

    assert proxy.patch(url, json={"name": "A"}, headers=USER).status_code == 403
    assert (
        proxy.patch(url, json={"name": "A"}, headers={**USER, "X-CSRF-Token": bobs}).status_code
        == 403
    )
    response = proxy.patch(url, json={"name": "A"}, headers={**USER, "X-CSRF-Token": csrf})
    assert response.status_code == 200


def test_no_password_login(app: FastAPI) -> None:
    response = from_(app, PROXY).post("/api/v1/auth/login", json={"password": "x"})

    assert response.status_code == 400


def test_open_links(app: FastAPI, make: Factories, session: Session) -> None:
    article = make.article(link="https://news.example/a", digest_date=date(2026, 10, 21))
    session.commit()
    signed = f"/open?id={article.id}&sig={link_signature(SECRET, article.id)}"
    stranger, proxy = from_(app, STRANGER), from_(app, PROXY)

    assert stranger.get(signed).status_code == 302
    assert stranger.get(f"/open?id={article.id}", headers=USER).status_code == 401
    assert proxy.get(f"/open?id={article.id}", headers=USER).status_code == 302


def test_another_header_name(app: FastAPI, auth_settings: AuthSettings) -> None:
    auth_settings_with = auth_settings.model_copy(update={"header": "X-Forwarded-User"})
    app.state.auth.settings = auth_settings_with
    proxy = from_(app, PROXY)

    assert proxy.get("/api/v1/status", headers=USER).status_code == 401
    assert proxy.get("/api/v1/status", headers={"X-Forwarded-User": "alice"}).status_code == 200


@pytest.mark.parametrize(
    "authorization", ["Basic YWxpY2U6c2VjcmV0", "Bearer eyJhbGciOiJSUzI1NiJ9.proxy.token"]
)
def test_a_proxys_own_authorization_is_ignored(app: FastAPI, authorization: str) -> None:
    # e.g. oauth2-proxy passing on its access token, or basic auth at the proxy.
    proxy = from_(app, PROXY)

    response = proxy.get("/api/v1/status", headers={**USER, "Authorization": authorization})

    assert response.status_code == 200


def test_a_wrong_brzask_token_is_not_saved_by_the_proxy_user(app: FastAPI) -> None:
    proxy = from_(app, PROXY)

    response = proxy.get("/api/v1/status", headers={**USER, "Authorization": "Bearer brz_wrong"})

    assert response.status_code == 401
