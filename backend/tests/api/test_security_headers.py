import base64
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider

from brzask.api.app import create_app
from brzask.api.metrics import prometheus_reader
from brzask.api.security import app_policy, inline_script_hashes
from brzask.config.settings import AuthSettings, ServerSettings
from brzask.db.session import create_db_engine, session_factory

THEME = "document.documentElement.classList.toggle('dark', true)"
INDEX = (
    "<!doctype html><html><head><script>"
    + THEME
    + '</script><script type="module" src="./assets/index-a1b2c3.js"></script>'
    "</head><body></body></html>"
)


def sha256(script: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'"


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text(INDEX)
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-a1b2c3.js").write_text("console.log(1)")
    return tmp_path


def _client(web_dir: Path | None, auth: AuthSettings, base_url: str | None = None) -> TestClient:
    # These requests never reach the database; nothing listens on port 1.
    engine = create_db_engine("postgresql+psycopg://brzask:x@127.0.0.1:1/brzask")
    reader, registry = prometheus_reader()
    app = create_app(
        session_factory(engine),
        metrics_registry=registry,
        meter_provider=MeterProvider(metric_readers=[reader]),
        auth_settings=auth,
        server=ServerSettings.model_validate({"BASE_URL": base_url}),
        web_dir=web_dir,
    )
    return TestClient(app)


@pytest.fixture
def client(web_dir: Path, password_auth: AuthSettings) -> TestClient:
    return _client(web_dir, password_auth)


def directives(policy: str) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for part in policy.split(";"):
        name, *values = part.split()
        parsed[name] = values
    return parsed


def test_inline_scripts_are_hashed_and_bundles_are_not() -> None:
    assert inline_script_hashes(INDEX) == [sha256(THEME)]


def test_a_page_without_inline_scripts_has_no_hashes() -> None:
    assert inline_script_hashes("<html><head></head></html>") == []


def test_inline_script_with_attributes_and_case_is_hashed() -> None:
    page = '<SCRIPT nonce="x">a()</SCRIPT><script type="module" src=x.js></script>'

    assert inline_script_hashes(page) == [sha256("a()")]


def test_the_app_policy_allows_only_its_own_origin_and_the_hashed_scripts() -> None:
    policy = directives(app_policy(["'sha256-abc'"]))

    assert policy["default-src"] == ["'self'"]
    assert policy["script-src"] == ["'self'", "'sha256-abc'"]
    assert policy["connect-src"] == ["'self'"]
    assert policy["frame-ancestors"] == ["'none'"]
    assert policy["object-src"] == ["'none'"]
    assert policy["base-uri"] == ["'self'"]


@pytest.mark.parametrize("path", ["/", "/archive/2026-10-01", "/assets/index-a1b2c3.js"])
def test_the_app_is_served_under_its_policy(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    policy = directives(response.headers["content-security-policy"])
    assert policy["script-src"] == ["'self'", sha256(THEME)]


@pytest.mark.parametrize("path", ["/", "/healthz", "/api/v1/digests", "/api/v1/docs", "/nope.js"])
def test_every_response_gets_the_common_headers(client: TestClient, path: str) -> None:
    headers = client.get(path).headers

    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["x-frame-options"] == "DENY"
    assert "camera=()" in headers["permissions-policy"]


def test_api_responses_carry_the_app_policy(client: TestClient) -> None:
    response = client.get("/healthz")

    assert directives(response.headers["content-security-policy"])["default-src"] == ["'self'"]


def test_the_api_docs_may_load_swagger_from_its_cdn(client: TestClient) -> None:
    response = client.get("/api/v1/docs")

    assert response.status_code == 200
    policy = directives(response.headers["content-security-policy"])
    assert "https://cdn.jsdelivr.net" in policy["script-src"]
    assert "https://cdn.jsdelivr.net" in policy["style-src"]
    assert policy["frame-ancestors"] == ["'none'"]
    # The page's own policy holds nothing the app's would need relaxing for.
    assert "https://cdn.jsdelivr.net" not in client.get("/").headers["content-security-policy"]


def test_the_api_docs_keep_their_policy_under_a_prefix(
    web_dir: Path, password_auth: AuthSettings
) -> None:
    client = _client(web_dir, password_auth, "http://testserver/brzask/")

    for path in ("/brzask/api/v1/docs", "/api/v1/docs"):
        policy = client.get(path).headers["content-security-policy"]
        assert "https://cdn.jsdelivr.net" in policy, path


def test_without_a_web_app_scripts_come_only_from_its_origin(password_auth: AuthSettings) -> None:
    client = _client(None, password_auth)

    policy = directives(client.get("/healthz").headers["content-security-policy"])
    assert policy["script-src"] == ["'self'"]
