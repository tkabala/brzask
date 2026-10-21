from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider

from brzask.api.app import create_app
from brzask.api.metrics import prometheus_reader
from brzask.config.settings import AuthSettings
from brzask.db.session import create_db_engine, session_factory

INDEX = "<!doctype html><title>brzask</title>"


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text(INDEX)
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-a1b2c3.js").write_text("console.log(1)")
    return tmp_path


@pytest.fixture
def client(web_dir: Path, password_auth: AuthSettings) -> TestClient:
    # These requests never reach the database; nothing listens on port 1.
    engine = create_db_engine("postgresql+psycopg://brzask:x@127.0.0.1:1/brzask")
    reader, registry = prometheus_reader()
    app = create_app(
        session_factory(engine),
        metrics_registry=registry,
        meter_provider=MeterProvider(metric_readers=[reader]),
        auth_settings=password_auth,
        web_dir=web_dir,
    )
    return TestClient(app)


def test_root_serves_the_app(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/archive/2026-10-01", "/sources", "/search?q=rust"])
def test_app_routes_serve_the_app(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.text == INDEX


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
