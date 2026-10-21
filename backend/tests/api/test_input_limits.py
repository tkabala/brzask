"""Values the schema allows but the database could not store or compare."""

import pytest
from fastapi.testclient import TestClient

from brzask.api.pagination import encode_cursor
from tests.factories import Factories


@pytest.mark.parametrize(
    "body",
    [
        {"topic": "a\x00b"},
        {"topic": "ok", "keywords": ["k\x00"]},
        {"topic": "ok", "notes": "\x00"},
    ],
)
def test_nul_characters_are_a_validation_error(client: TestClient, body: dict[str, object]) -> None:
    response = client.post("/api/v1/interests", json=body)

    assert response.status_code == 422


def test_nul_characters_elsewhere(client: TestClient, make: Factories) -> None:
    source = make.source()

    assert client.patch(f"/api/v1/sources/{source.id}", json={"name": "a\x00"}).status_code == 422
    assert client.post("/api/v1/sources", json={"url": "https://a\x00.example"}).status_code == 422
    assert client.get("/api/v1/search", params={"q": "a\x00"}).status_code == 422
    assert (
        client.get("/api/v1/sources", params={"cursor": "WyJhXHUwMDAwIiwiMSJd"}).status_code == 400
    )


def test_cursor_with_an_id_beyond_bigint_is_a_bad_request(client: TestClient) -> None:
    cursor = encode_cursor(["a", str(2**64)])

    assert client.get("/api/v1/sources", params={"cursor": cursor}).status_code == 400
