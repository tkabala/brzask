from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.metrics import NoOpMeterProvider
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker
from structlog.testing import capture_logs

from brzask.api.app import create_app
from brzask.api.metrics import prometheus_reader
from brzask.config.settings import AuthSettings
from brzask.db.models import LoginSession
from brzask.services.auth import FAILURES_PER_CLIENT, link_signature
from tests.api.conftest import PASSWORD, SECRET
from tests.factories import Factories


@pytest.fixture
def auth_settings(password_auth: AuthSettings) -> AuthSettings:
    return password_auth


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # Over HTTPS, as the session cookie is Secure.
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def log_in(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    token: str = response.json()["csrf_token"]
    return token


def test_api_needs_a_login(client: TestClient) -> None:
    response = client.get("/api/v1/status")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert client.get("/api/v1/auth/session").json() == {
        "mode": "password",
        "authenticated": False,
        "user": None,
        "csrf_token": None,
        "expires_at": None,
    }


def test_probes_and_the_document_need_no_login(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/v1/openapi.json").status_code == 200


def test_login_sets_a_session_cookie(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    cookies = {c.split("=", 1)[0]: c for c in response.headers.get_list("set-cookie")}
    session_cookie = cookies["brzask_session"].lower()
    assert "httponly" in session_cookie
    assert "secure" in session_cookie
    assert "samesite=lax" in session_cookie
    assert "max-age=2592000" in session_cookie  # 30 days
    assert "httponly" not in cookies["brzask_csrf"].lower()  # the page reads it
    assert client.get("/api/v1/status").status_code == 200
    state = client.get("/api/v1/auth/session").json()
    assert (state["authenticated"], state["csrf_token"]) == (True, body["csrf_token"])


def test_wrong_password(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"password": "guess"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Wrong password."
    assert "set-cookie" not in response.headers


def test_lockout_after_repeated_failures(client: TestClient) -> None:
    for _ in range(FAILURES_PER_CLIENT):
        assert client.post("/api/v1/auth/login", json={"password": "guess"}).status_code == 401

    # Even the right password is not checked while locked out.
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})

    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 15 * 60
    assert "set-cookie" not in response.headers


def test_changes_need_the_csrf_token(client: TestClient, make: Factories) -> None:
    source = make.source("Old")
    csrf = log_in(client)
    url = f"/api/v1/sources/{source.id}"

    missing = client.patch(url, json={"name": "New"})
    wrong = client.patch(url, json={"name": "New"}, headers={"X-CSRF-Token": "0" * 64})
    right = client.patch(url, json={"name": "New"}, headers={"X-CSRF-Token": csrf})

    assert (missing.status_code, wrong.status_code, right.status_code) == (403, 403, 200)
    assert "X-CSRF-Token" in missing.json()["detail"]
    assert client.get("/api/v1/status").status_code == 200  # reads need none


def test_logout_ends_the_session_everywhere(client: TestClient) -> None:
    csrf = log_in(client)
    token = client.cookies["brzask_session"]

    assert client.post("/api/v1/auth/logout").status_code == 403  # CSRF applies
    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 204
    assert client.get("/api/v1/status").status_code == 401
    # A copy of the cookie no longer works either.
    copied = TestClient(
        client.app, base_url="https://testserver", cookies={"brzask_session": token}
    )
    assert copied.get("/api/v1/status").status_code == 401


def test_expired_session(client: TestClient, session: Session) -> None:
    log_in(client)
    session.execute(update(LoginSession).values(expires_at=datetime.now(UTC) - timedelta(1)))
    session.commit()

    assert client.get("/api/v1/status").status_code == 401
    assert client.get("/api/v1/auth/session").json()["authenticated"] is False


def test_forged_cookie(client: TestClient) -> None:
    client.cookies.set("brzask_session", "made-up")

    assert client.get("/api/v1/status").status_code == 401


def test_open_links_are_signed(client: TestClient, make: Factories, session: Session) -> None:
    article = make.article(link="https://news.example/a", digest_date=date(2026, 10, 21))
    session.commit()
    signed = f"/open?id={article.id}&sig={link_signature(SECRET, article.id)}"

    # From a feed reader: no session, a signed link.
    assert client.get(signed).status_code == 302
    assert client.get(f"/open?id={article.id}").status_code == 401
    assert client.get(f"/open?id={article.id}&sig=0123456789abcdef").status_code == 401
    assert client.head(f"/open?id={article.id}").status_code == 401

    log_in(client)
    assert client.get(f"/open?id={article.id}").status_code == 302  # a session is enough
    digest = client.get("/api/v1/digests/2026-10-21").json()
    assert digest["articles"][0]["open_url"] == signed


def test_no_password_login_in_mode_none(sessions: sessionmaker[Session]) -> None:
    _, registry = prometheus_reader()
    app = create_app(
        sessions,
        metrics_registry=registry,
        meter_provider=NoOpMeterProvider(),
        auth_settings=AuthSettings(mode="none"),
    )
    client = TestClient(app)

    assert client.post("/api/v1/auth/login", json={"password": "x"}).status_code == 400
    assert client.get("/api/v1/auth/session").json()["authenticated"] is True
    assert client.get("/api/v1/status").status_code == 200


def test_mode_none_warns_at_startup(sessions: sessionmaker[Session]) -> None:
    _, registry = prometheus_reader()
    with capture_logs() as logs:
        create_app(
            sessions,
            metrics_registry=registry,
            meter_provider=NoOpMeterProvider(),
            auth_settings=AuthSettings(mode="none"),
        )

    assert any(entry["log_level"] == "warning" and "NO LOGIN" in entry["event"] for entry in logs)


def test_cookie_without_secure_for_plain_http(
    sessions: sessionmaker[Session], password_auth: AuthSettings
) -> None:
    _, registry = prometheus_reader()
    settings = password_auth.model_copy(update={"cookie_secure": "false"})
    app = create_app(
        sessions,
        metrics_registry=registry,
        meter_provider=NoOpMeterProvider(),
        auth_settings=settings,
    )
    client = TestClient(app)  # plain http

    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})

    assert "secure" not in response.headers["set-cookie"].lower()
    assert client.get("/api/v1/status").status_code == 200


def test_lockout_is_per_client_behind_a_trusted_proxy(
    sessions: sessionmaker[Session], password_auth: AuthSettings
) -> None:
    _, registry = prometheus_reader()
    settings = AuthSettings.model_validate(
        {**password_auth.model_dump(exclude={"trusted_proxies"}), "TRUSTED_PROXIES": "10.0.0.0/24"}
    )
    app = create_app(
        sessions,
        metrics_registry=registry,
        meter_provider=NoOpMeterProvider(),
        auth_settings=settings,
    )
    proxy = TestClient(app, base_url="https://testserver", client=("10.0.0.5", 41000))

    def attempt(client: str, password: str) -> int:
        response = proxy.post(
            "/api/v1/auth/login",
            json={"password": password},
            headers={"X-Forwarded-For": client},
        )
        return response.status_code

    for _ in range(FAILURES_PER_CLIENT):
        attempt("198.51.100.1", "guess")

    assert attempt("198.51.100.1", PASSWORD) == 429
    assert attempt("198.51.100.2", PASSWORD) == 200


def test_cookie_is_secure_when_the_login_came_over_https(
    sessions: sessionmaker[Session], password_auth: AuthSettings
) -> None:
    _, registry = prometheus_reader()
    settings = AuthSettings.model_validate(
        {**password_auth.model_dump(exclude={"trusted_proxies"}), "TRUSTED_PROXIES": "10.0.0.0/24"}
    )
    app = create_app(
        sessions,
        metrics_registry=registry,
        meter_provider=NoOpMeterProvider(),
        auth_settings=settings,
    )

    def secure(client: TestClient, headers: dict[str, str] | None = None) -> bool:
        response = client.post("/api/v1/auth/login", json={"password": PASSWORD}, headers=headers)
        assert response.status_code == 200
        return "secure" in response.headers["set-cookie"].lower()

    assert secure(TestClient(app, base_url="https://testserver"))
    assert not secure(TestClient(app))  # plain HTTP, e.g. localhost in development
    proxy = TestClient(app, client=("10.0.0.5", 41000))
    assert secure(proxy, {"X-Forwarded-Proto": "https"})
    assert not secure(proxy, {"X-Forwarded-Proto": "http"})
    # Only a trusted proxy is believed.
    stranger = TestClient(app, client=("203.0.113.9", 41000))
    assert not secure(stranger, {"X-Forwarded-Proto": "https"})
