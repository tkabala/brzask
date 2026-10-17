"""Structured logging.

Everything is logged through structlog, including libraries that use the standard
``logging`` module: one JSON object per line in production, readable lines on a
terminal. IDs bound to the context (a request ID, a run ID) are added to every
line logged while handling that request or run.
"""

import logging
import re
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any, Literal, TextIO

import structlog
from structlog.contextvars import bound_contextvars
from structlog.typing import Processor

LogFormat = Literal["auto", "json", "console"]

# Libraries that log every request at INFO; their warnings still come through.
_QUIET_LOGGERS = ("httpx", "httpcore", "apscheduler.executors.default")


def configure_logging(
    level: str = "INFO", log_format: LogFormat = "auto", stream: TextIO | None = None
) -> None:
    """Route all logging to ``stream`` (stderr by default) through structlog."""
    stream = stream or sys.stderr
    console = log_format == "console" or (log_format == "auto" and stream.isatty())

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    output: list[Processor] = (
        [structlog.dev.ConsoleRenderer()]
        if console
        else [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ]
    )

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *output],
        )
    )
    root = logging.getLogger()
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger


def new_id() -> str:
    return uuid.uuid4().hex


# --- Runs ------------------------------------------------------------------------


@contextmanager
def logged_run(pipeline: str, run_id: str | None = None) -> Iterator[str]:
    """Log the start and end of a pipeline run, with its run ID on every line inside."""
    run_id = run_id or new_id()
    log = get_logger("brzask.run")
    with bound_contextvars(run_id=run_id, pipeline=pipeline):
        started = time.perf_counter()
        log.info("run started")
        try:
            yield run_id
        except Exception:
            log.exception("run failed", duration_ms=_elapsed_ms(started))
            raise
        except BaseException:
            log.warning("run interrupted", duration_ms=_elapsed_ms(started))
            raise
        log.info("run finished", duration_ms=_elapsed_ms(started))


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


# --- Requests --------------------------------------------------------------------

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

REQUEST_ID_HEADER = b"x-request-id"
# Incoming IDs end up in every log line, so only plain tokens are accepted.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestContextMiddleware:
    """Binds a request ID to the log context and returns it in ``X-Request-ID``.

    An ``X-Request-ID`` set by a reverse proxy is kept when it is a plain token;
    otherwise a new ID is generated.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or new_id()

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [*message.get("headers", []), (REQUEST_ID_HEADER, request_id.encode())]
                message = {**message, "headers": headers}
            await send(message)

        with bound_contextvars(request_id=request_id):
            await self.app(scope, receive, send_with_request_id)


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == REQUEST_ID_HEADER:
            candidate = value.decode("latin-1")
            return candidate if _VALID_REQUEST_ID.match(candidate) else None
    return None
