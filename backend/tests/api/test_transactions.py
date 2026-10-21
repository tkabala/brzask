"""A route's transaction is committed before its response leaves.

Otherwise a client that acts on the response at once (logging in, then
asking whether it is logged in) can reach the database before the commit.
"""

from collections.abc import Iterator, MutableMapping
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from brzask.config.settings import AuthSettings
from tests.api.conftest import PASSWORD


@pytest.fixture
def auth_settings(password_auth: AuthSettings) -> AuthSettings:
    return password_auth


@pytest.fixture
def order() -> Iterator[list[str]]:
    events: list[str] = []

    def committed(_session: Session) -> None:
        events.append("commit")

    event.listen(Session, "after_commit", committed)
    yield events
    event.remove(Session, "after_commit", committed)


def test_commit_comes_before_the_response(app: FastAPI, order: list[str]) -> None:
    async def recording(scope: Any, receive: Any, send: Any) -> None:
        async def send_and_note(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                order.append("response")
            await send(message)

        await app(scope, receive, send_and_note)

    client = TestClient(recording, base_url="https://testserver")

    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})

    assert response.status_code == 200
    assert order == ["commit", "response"]
