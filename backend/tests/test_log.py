import asyncio
import io
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
import structlog

from brzask.log import (
    Message,
    Receive,
    RequestContextMiddleware,
    Scope,
    Send,
    configure_logging,
    get_logger,
    logged_run,
)


@pytest.fixture
def output() -> Iterator[io.StringIO]:
    """JSON log output; logging is reset afterwards."""
    stream = io.StringIO()
    configure_logging("INFO", "json", stream)
    yield stream
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
    logging.getLogger().handlers.clear()


def lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_json_lines_carry_level_logger_timestamp_and_fields(output: io.StringIO) -> None:
    get_logger("brzask.test").info("fetched feed", entries=12)

    [line] = lines(output)
    assert line["event"] == "fetched feed"
    assert line["entries"] == 12
    assert line["level"] == "info"
    assert line["logger"] == "brzask.test"
    assert line["timestamp"].endswith("Z")


def test_non_ascii_text_is_kept_readable(output: io.StringIO) -> None:
    get_logger("brzask.test").info("selected", title="Zażółć gęślą jaźń")

    assert "Zażółć gęślą jaźń" in output.getvalue()


def test_standard_library_logs_are_rendered_the_same_way(output: io.StringIO) -> None:
    logging.getLogger("some.library").warning("slow response: %s s", 3)

    [line] = lines(output)
    assert line["event"] == "slow response: 3 s"
    assert line["level"] == "warning"
    assert line["logger"] == "some.library"


def test_level_filters_lower_levels() -> None:
    stream = io.StringIO()
    configure_logging("WARNING", "json", stream)
    log = get_logger("brzask.test")

    log.info("hidden")
    log.warning("shown")

    assert [line["event"] for line in lines(stream)] == ["shown"]
    logging.getLogger().handlers.clear()


def test_console_format_is_not_json() -> None:
    stream = io.StringIO()
    configure_logging("INFO", "console", stream)

    get_logger("brzask.test").info("hello", answer=42)

    text = stream.getvalue()
    assert "hello" in text
    assert "answer" in text
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)
    logging.getLogger().handlers.clear()


def test_auto_format_uses_json_when_not_a_terminal(output: io.StringIO) -> None:
    stream = io.StringIO()
    configure_logging("INFO", "auto", stream)

    get_logger("brzask.test").info("hello")

    assert json.loads(stream.getvalue())["event"] == "hello"


# --- Runs ------------------------------------------------------------------------


def test_run_logs_one_start_and_one_finish_line_with_its_run_id(output: io.StringIO) -> None:
    with logged_run("digest") as run_id:
        get_logger("brzask.digest").info("ranked", candidates=180)

    start, inner, finish = lines(output)
    assert start["event"] == "run started"
    assert finish["event"] == "run finished"
    assert isinstance(finish["duration_ms"], int)
    for line in (start, inner, finish):
        assert line["run_id"] == run_id
        assert line["pipeline"] == "digest"


def test_run_id_can_be_given(output: io.StringIO) -> None:
    with logged_run("review", run_id="abc123"):
        pass

    assert {line["run_id"] for line in lines(output)} == {"abc123"}


def test_run_id_is_unbound_after_the_run(output: io.StringIO) -> None:
    with logged_run("digest"):
        pass
    get_logger("brzask.test").info("after")

    assert "run_id" not in lines(output)[-1]


def test_failed_run_logs_the_error_and_reraises(output: io.StringIO) -> None:
    with pytest.raises(RuntimeError), logged_run("digest") as run_id:
        raise RuntimeError("LLM returned garbage")

    _start, failure = lines(output)
    assert failure["event"] == "run failed"
    assert failure["level"] == "error"
    assert failure["run_id"] == run_id
    assert "LLM returned garbage" in json.dumps(failure["exception"])


# --- Requests --------------------------------------------------------------------


def call(app: RequestContextMiddleware, headers: list[tuple[bytes, bytes]]) -> list[Message]:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(app({"type": "http", "headers": headers}, receive, send))
    return sent


async def logging_app(scope: Scope, receive: Receive, send: Send) -> None:
    get_logger("brzask.api").info("handling request")
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def response_request_id(sent: list[Message]) -> str:
    headers = dict(sent[0]["headers"])
    value: bytes = headers[b"x-request-id"]
    return value.decode()


def test_request_id_is_generated_logged_and_returned(output: io.StringIO) -> None:
    sent = call(RequestContextMiddleware(logging_app), headers=[])

    [line] = lines(output)
    assert line["request_id"] == response_request_id(sent)
    assert len(line["request_id"]) == 32


def test_request_id_from_a_proxy_is_kept(output: io.StringIO) -> None:
    sent = call(RequestContextMiddleware(logging_app), headers=[(b"x-request-id", b"proxy-42")])

    assert response_request_id(sent) == "proxy-42"
    assert lines(output)[0]["request_id"] == "proxy-42"


def test_unsafe_request_id_is_replaced(output: io.StringIO) -> None:
    sent = call(
        RequestContextMiddleware(logging_app),
        headers=[(b"x-request-id", b'evil"\nlevel=error')],
    )

    assert response_request_id(sent) != 'evil"\nlevel=error'
    assert len(response_request_id(sent)) == 32


def test_non_http_scopes_pass_through() -> None:
    seen: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    async def receive() -> Message:
        return {}

    async def send(message: Message) -> None:
        pass

    asyncio.run(RequestContextMiddleware(app)({"type": "lifespan"}, receive, send))

    assert seen == ["lifespan"]
