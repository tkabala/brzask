"""An MCP client talking to the app in process, with the app's lifespan running."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult
from sqlalchemy.orm import Session

from brzask.config.settings import AuthSettings
from brzask.db.models import TokenScope
from brzask.services.tokens import create_token

type Connect = Callable[[str | None], AbstractAsyncContextManager[Client]]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def auth_settings(password_auth: AuthSettings) -> AuthSettings:
    """With a login, so tokens decide what a call may do (no login lets everything through)."""
    return password_auth


def http_client(app: FastAPI, token: str | None) -> httpx2.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test", headers=headers
    )


@pytest.fixture
async def running_app(app: FastAPI) -> AsyncIterator[FastAPI]:
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
def connect(running_app: FastAPI) -> Connect:
    @asynccontextmanager
    async def connected(token: str | None) -> AsyncIterator[Client]:
        async with http_client(running_app, token) as http:
            transport = streamable_http_client("http://test/mcp", http_client=http)
            async with Client(transport) as client:
                yield client

    return connected


@pytest.fixture
def read_token(session: Session) -> str:
    return create_token(session, "reader", TokenScope.READ, actor="test")[1]


@pytest.fixture
def write_token(session: Session) -> str:
    return create_token(session, "claude", TokenScope.WRITE, actor="test")[1]


@pytest.fixture
def propose_token(session: Session) -> str:
    return create_token(session, "helper", TokenScope.PROPOSE, actor="test")[1]


def error_text(result: CallToolResult) -> str:
    assert result.is_error, result
    text = result.content[0]
    return str(getattr(text, "text", text))


def data(result: CallToolResult) -> Any:
    assert not result.is_error, result.content
    return result.structured_content
