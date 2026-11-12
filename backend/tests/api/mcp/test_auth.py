import logging
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from brzask.config.settings import AuthSettings
from brzask.db.models import TokenScope
from brzask.mcp.content import cap
from brzask.mcp.server import AgentIdentity, identity_scope, require_change, require_write
from brzask.services.tokens import create_token, revoke_token
from tests.api.mcp.conftest import Connect, data, error_text, http_client

pytestmark = pytest.mark.anyio

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
ACCEPT = {"Accept": "application/json, text/event-stream"}


async def post(app: FastAPI, token: str | None, path: str = "/mcp", **kwargs: object) -> object:
    async with http_client(app, token) as http:
        return await http.post(path, json=INITIALIZE, headers=ACCEPT, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("token", [None, "junk", "brz_unknown"])
async def test_a_request_without_a_valid_token_is_refused(
    running_app: FastAPI, token: str | None
) -> None:
    response = await post(running_app, token)

    assert response.status_code == 401  # type: ignore[attr-defined]
    assert response.headers["content-type"] == "application/problem+json"  # type: ignore[attr-defined]
    assert response.headers["www-authenticate"] == "Bearer"  # type: ignore[attr-defined]
    assert "Bearer brz_" in response.json()["detail"]  # type: ignore[attr-defined]


async def test_feed_and_revoked_tokens_are_refused(running_app: FastAPI, session: Session) -> None:
    feed = create_token(session, "reader-app", TokenScope.FEED, actor="test")[1]
    revoked = create_token(session, "old", TokenScope.WRITE, actor="test")[1]
    revoke_token(session, "old", datetime.now(UTC), actor="test")

    for token in (feed, revoked):
        assert (await post(running_app, token)).status_code == 401  # type: ignore[attr-defined]


async def test_a_token_in_the_query_is_not_accepted(running_app: FastAPI, read_token: str) -> None:
    response = await post(running_app, None, path=f"/mcp?token={read_token}")

    assert response.status_code == 401  # type: ignore[attr-defined]


async def test_a_read_token_lists_the_tools(connect: Connect, read_token: str) -> None:
    async with connect(read_token) as client:
        tools = await client.list_tools()
        assert "get_status" in {tool.name for tool in tools.tools}
        assert client.instructions is not None
        assert "external" in client.instructions


async def test_post_to_mcp_is_not_redirected(running_app: FastAPI, read_token: str) -> None:
    response = await post(running_app, read_token)

    assert response.status_code == 200  # type: ignore[attr-defined]


@pytest.mark.parametrize("base_url_setting", ["https://home.example/brzask/"])
@pytest.mark.parametrize("path", ["/brzask/mcp", "/mcp"])
async def test_served_under_a_sub_path_and_without_it(
    running_app: FastAPI, read_token: str, path: str
) -> None:
    response = await post(running_app, read_token, path=path)

    assert response.status_code == 200  # type: ignore[attr-defined]


@pytest.mark.parametrize("auth_settings", [AuthSettings(mode="none")])
async def test_without_login_every_call_is_local_and_may_write(connect: Connect) -> None:
    async with connect(None) as client:
        result = await client.call_tool("get_status", {})
        data(result)


def test_require_write_refuses_a_read_identity() -> None:
    with (
        identity_scope(AgentIdentity("reader", TokenScope.READ)),
        pytest.raises(Exception, match="this needs a write token"),
    ):
        require_write()


def test_require_change_takes_write_and_propose_tokens() -> None:
    with identity_scope(AgentIdentity("helper", TokenScope.PROPOSE)):
        assert require_change().proposes
        with pytest.raises(Exception, match="this needs a write token"):
            require_write()
    with (
        identity_scope(AgentIdentity("reader", TokenScope.READ)),
        pytest.raises(Exception, match="this needs a write or propose token"),
    ):
        require_change()


def test_require_write_gives_the_actor() -> None:
    with identity_scope(AgentIdentity("claude", TokenScope.WRITE)):
        assert require_write().actor == "agent:claude"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, (None, False)),
        ("short", ("short", False)),
        ("x" * 8000, ("x" * 8000, False)),
        ("x" * 8001, ("x" * 8000, True)),
    ],
)
def test_cap(text: str | None, expected: tuple[str | None, bool]) -> None:
    assert cap(text) == expected


def test_building_the_server_keeps_the_logging_setup(app: FastAPI) -> None:
    from brzask.mcp.server import INSTRUCTIONS  # noqa: F401  (imported after app built)

    root = logging.getLogger()
    assert not any(type(h).__name__ == "RichHandler" for h in root.handlers)


async def test_a_failing_tool_reads_as_a_tool_error(connect: Connect, read_token: str) -> None:
    async with connect(read_token) as client:
        result = await client.call_tool("no_such_tool", {})
        assert "no_such_tool" in error_text(result)
