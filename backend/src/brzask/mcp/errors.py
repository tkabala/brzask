"""Errors a tool reports to the agent, rather than as a crash."""

from collections.abc import Iterator
from contextlib import contextmanager

from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy.exc import OperationalError

from brzask.services.errors import ServiceError


@contextmanager
def service_errors() -> Iterator[None]:
    """Turn what the services refuse into tool errors the agent can read and act on.

    Anything else is a crash: the SDK logs it with its traceback and tells the
    agent only that the tool failed.
    """
    try:
        yield
    except ServiceError as error:  # NotFoundError and ConflictError included
        raise ToolError(str(error)) from error
    except OperationalError as error:
        raise ToolError("database unavailable") from error
