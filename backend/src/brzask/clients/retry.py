"""Retrying calls to OpenAI-compatible APIs."""

import random
from collections.abc import Callable

import openai

from brzask.log import get_logger

log = get_logger(__name__)

# One call plus three retries; with the delays below a call gives up after about
# 14 s of waiting, which covers short provider hiccups without stalling a run.
ATTEMPTS = 4
BASE_DELAY_SECONDS = 2.0
MAX_DELAY_SECONDS = 30.0


class APIError(Exception):
    """The API failed or kept failing; the message says why."""


class EmptyResponseError(Exception):
    """A 200 response without a result; providers send these when an upstream model fails."""


# Errors worth another attempt: the request may succeed unchanged.
_RETRYABLE = (
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
    EmptyResponseError,
)


def call_with_retries[T](
    call: Callable[[], T],
    *,
    purpose: str,
    error: type[APIError],
    sleep: Callable[[float], None],
) -> T:
    """Run `call`, retrying temporary failures; other API errors fail at once as `error`."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return call()
        except _RETRYABLE as failure:
            if attempt == ATTEMPTS:
                raise error(f"{purpose}: gave up after {ATTEMPTS} attempts: {failure}") from failure
            delay = _delay(attempt, failure)
            log.warning(
                "api call failed, retrying",
                purpose=purpose,
                attempt=attempt,
                delay_s=round(delay, 1),
                error=str(failure),
            )
            sleep(delay)
        except openai.APIError as failure:
            raise error(f"{purpose}: {failure}") from failure
    raise AssertionError("unreachable")  # pragma: no cover


def _delay(attempt: int, error: Exception) -> float:
    """The server's Retry-After when given (capped), else exponential backoff with jitter."""
    if isinstance(error, openai.APIStatusError):
        retry_after = error.response.headers.get("retry-after")
        try:
            if retry_after is not None:
                return min(float(retry_after), MAX_DELAY_SECONDS)
        except ValueError:
            pass  # an HTTP date; fall back to backoff
    delay: float = min(BASE_DELAY_SECONDS * 2 ** (attempt - 1), MAX_DELAY_SECONDS)
    return delay * random.uniform(0.8, 1.2)  # noqa: S311  (jitter, not security)
