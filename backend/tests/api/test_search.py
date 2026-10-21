import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import FakeEmbedder
from tests.factories import TEST_MODEL, Factories, unit_vector


@pytest.fixture(autouse=True)
def test_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL", TEST_MODEL)


def test_finds_the_closest_articles_with_a_query_embedding(
    client: TestClient,
    make: Factories,
    query_vectors: dict[str, list[float]],
    embedders: dict[str, FakeEmbedder],
) -> None:
    near = make.article(title="Postgres 18", embedding=unit_vector(1, 0.1))
    far = make.article(title="Rust", embedding=unit_vector(0, 1))
    make.article(title="Other model", embedding=unit_vector(1, 0), embedding_model="other")
    query_vectors["new postgres release"] = unit_vector(1, 0)

    body = client.get("/api/v1/search", params={"q": " new postgres release "}).json()

    assert body["model"] == TEST_MODEL
    assert [hit["article"]["id"] for hit in body["items"]] == [near.id, far.id]
    assert body["items"][0]["similarity"] == pytest.approx(0.995, abs=1e-3)
    assert embedders[TEST_MODEL].calls == [(["new postgres release"], "query")]


def test_limit(client: TestClient, make: Factories) -> None:
    for _ in range(3):
        make.article(embedding=unit_vector(1))

    body = client.get("/api/v1/search", params={"q": "x", "limit": "2"}).json()

    assert len(body["items"]) == 2


def test_blank_query_is_a_bad_request(client: TestClient) -> None:
    assert client.get("/api/v1/search", params={"q": "  "}).status_code == 400
    assert client.get("/api/v1/search", params={"q": ""}).status_code == 422


def test_failing_embedding_api_is_a_bad_gateway(
    client: TestClient, embedders: dict[str, FakeEmbedder]
) -> None:
    client.get("/api/v1/search", params={"q": "warm up"})
    embedders[TEST_MODEL].fail = True

    response = client.get("/api/v1/search", params={"q": "postgres"})

    assert response.status_code == 502
    assert response.headers["content-type"] == "application/problem+json"
    assert "embedding API failed" in response.json()["detail"]
