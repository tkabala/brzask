from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider

from brzask.api.app import create_app
from brzask.api.metrics import prometheus_reader
from brzask.config.settings import AuthSettings, ServerSettings
from brzask.db.session import create_db_engine, session_factory

INDEX = "<!doctype html><html><head><title>brzask</title></head><body></body></html>"


def served(base: str) -> str:
    """INDEX as the server sends it, with its base element."""
    return INDEX.replace("<head>", f'<head><base href="{base}">')


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text(INDEX)
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path / "sw.js").write_text("self.skipWaiting()")
    (tmp_path / "manifest.webmanifest").write_text('{"name": "brzask"}')
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-a1b2c3.js").write_text("console.log(1)")
    return tmp_path


def _client(web_dir: Path, auth: AuthSettings, base_url: str | None = None) -> TestClient:
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


@pytest.fixture
def prefixed(web_dir: Path, password_auth: AuthSettings) -> TestClient:
    """The app served at http://testserver/brzask/."""
    return _client(web_dir, password_auth, "http://testserver/brzask/")


def test_root_serves_the_app(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.text == served("/")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("path", ["/archive/2026-10-01", "/sources", "/search?q=rust"])
def test_app_routes_serve_the_app(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.text == served("/")


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/sw.js", "text/javascript"),
        ("/manifest.webmanifest", "application/manifest+json"),
    ],
)
def test_installable_app_files_are_revalidated(
    client: TestClient, path: str, content_type: str
) -> None:
    # A new service worker or manifest must reach installed apps on their next open.
    response = client.get(path)

    assert response.status_code == 200
    assert response.text != served("/")
    assert response.headers["content-type"].startswith(content_type)
    assert response.headers["cache-control"] == "no-cache"


def test_hashed_assets_are_cached_for_good(client: TestClient) -> None:
    response = client.get("/assets/index-a1b2c3.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_other_files_are_revalidated(client: TestClient) -> None:
    response = client.get("/favicon.svg")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_a_missing_asset_is_not_found(client: TestClient) -> None:
    # An old bundle name must not load index.html as JavaScript.
    assert client.get("/assets/index-old.js").status_code == 404


@pytest.mark.parametrize("path", ["/api", "/api/v1/nothing-here"])
def test_unknown_api_paths_stay_problems(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


def test_api_routes_win_over_the_app(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    # The API still asks for a login; the app itself does not.
    assert client.get("/api/v1/status").status_code == 401


@pytest.mark.parametrize(
    ("method", "path"), [("HEAD", "/readyz"), ("POST", "/healthz"), ("POST", "/api/v1/status")]
)
def test_api_routes_answer_other_methods_themselves(
    client: TestClient, method: str, path: str
) -> None:
    # Not index.html: a HEAD probe must not pass while the database is down.
    response = client.request(method, path)

    assert response.status_code == 405
    assert response.headers["allow"] == "GET"


def test_files_outside_the_app_are_not_served(client: TestClient, web_dir: Path) -> None:
    (web_dir.parent / "secret.txt").write_text("secret")

    response = client.get("/..%2Fsecret.txt")

    assert "secret" not in response.text


def test_a_directory_without_an_index_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"no index\.html"):
        create_app(
            session_factory(create_db_engine("postgresql+psycopg://x:x@127.0.0.1:1/x")),
            metrics_registry=prometheus_reader()[1],
            auth_settings=AuthSettings(mode="none"),
            web_dir=tmp_path,
        )


# --- Under a path prefix ---------------------------------------------------------


def test_prefixed_index_gets_its_base(prefixed: TestClient) -> None:
    response = prefixed.get("/brzask/")

    assert response.status_code == 200
    assert response.text == served("/brzask/")
    assert response.headers["cache-control"] == "no-cache"


def test_existing_base_element_is_replaced(web_dir: Path, password_auth: AuthSettings) -> None:
    (web_dir / "index.html").write_text(INDEX.replace("<head>", '<head><base href="/" />'))

    response = _client(web_dir, password_auth, "http://testserver/brzask/").get("/brzask/")

    assert response.text == served("/brzask/")


def test_an_index_without_a_head_is_rejected(web_dir: Path, password_auth: AuthSettings) -> None:
    (web_dir / "index.html").write_text("<!doctype html><title>x</title>")

    with pytest.raises(RuntimeError, match="<head>"):
        _client(web_dir, password_auth)


def test_prefixed_deep_link_serves_the_app(prefixed: TestClient) -> None:
    response = prefixed.get("/brzask/archive/2026-10-01")

    assert response.status_code == 200
    assert response.text == served("/brzask/")


@pytest.mark.parametrize("prefix", ["/brzask", ""])
def test_prefix_passed_through_or_stripped(prefixed: TestClient, prefix: str) -> None:
    # Some proxies pass /brzask/... on unchanged, others strip the prefix.
    assert prefixed.get(f"{prefix}/api/v1/auth/session").status_code == 200
    asset = prefixed.get(f"{prefix}/assets/index-a1b2c3.js")
    assert asset.status_code == 200
    assert asset.text == "console.log(1)"
    assert prefixed.get(f"{prefix}/archive/2026-10-01").text == served("/brzask/")
    assert prefixed.get(f"{prefix}/api/v1/nothing-here").status_code == 404


def test_prefix_without_slash_redirects(prefixed: TestClient) -> None:
    response = prefixed.get("/brzask?signin", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "/brzask/?signin"


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/metrics"])
def test_probes_answer_without_the_prefix(prefixed: TestClient, path: str) -> None:
    # Container healthchecks and scrapers keep their paths; /readyz is 503 here
    # only because these tests have no database.
    assert prefixed.get(path).status_code in (200, 503)
    assert prefixed.get(path).headers["content-type"] != "text/html; charset=utf-8"
