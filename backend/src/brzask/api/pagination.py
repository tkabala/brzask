"""Cursor pagination.

A list answers with one page of `items` and a `next_cursor`; passing it back
as `cursor` returns the following page, and it is null on the last one. The
cursor is opaque to clients: it encodes the sort key of the last item, so
pages stay consistent while new rows arrive (no offsets that shift).
"""

import base64
import json
from collections.abc import Callable, Sequence
from http import HTTPStatus
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, Field

from brzask.api.problems import ProblemError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Items per page.")]
CursorParam = Annotated[
    str | None,
    Query(description="`next_cursor` of the previous page; leave out for the first page."),
]


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = Field(
        description="Pass as `cursor` for the next page; null on the last page."
    )


def encode_cursor(key: Sequence[str]) -> str:
    raw = json.dumps(list(key), separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor[K](cursor: str | None, parse: Callable[[list[str]], K]) -> K | None:
    """The sort key in `cursor`, built by `parse`; a cursor it rejects is a 400."""
    if cursor is None:
        return None
    # Bad base64, UTF-8 and JSON all raise ValueError, as `parse` should.
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        values = json.loads(raw)
        if not isinstance(values, list) or not all(
            isinstance(value, str) and "\x00" not in value for value in values
        ):
            raise ValueError("not a list of strings without NUL")
        return parse(values)
    except (ValueError, TypeError) as error:
        raise ProblemError(
            HTTPStatus.BAD_REQUEST, "The cursor is not valid; start again without it."
        ) from error


def page[T](
    rows: Sequence[T], limit: int, key: Callable[[T], Sequence[str]]
) -> tuple[list[T], str | None]:
    """Items of a page from `rows` fetched with `limit + 1`, and the next cursor."""
    items = list(rows[:limit])
    more = len(rows) > limit
    return items, encode_cursor(key(items[-1])) if more and items else None
