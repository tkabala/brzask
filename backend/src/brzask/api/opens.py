"""`/open`: follow an article's link and record the open.

Outside the versioned API, as its URLs end up in feed readers, mail and
bookmarks and must keep working.
"""

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from brzask.api import problems
from brzask.api.deps import DbSession
from brzask.services.opens import article_link, open_article
from brzask.services.refs import MAX_ID

router = APIRouter(tags=["articles"])

ArticleId = Annotated[int, Query(alias="id", ge=1, le=MAX_ID, description="Article ID.")]

# Every open must reach the server; a cached redirect would skip recording it.
NO_STORE = {"Cache-Control": "no-store"}


def open_url(article_id: int) -> str:
    """The path that opens an article, relative to the server."""
    return f"/open?id={article_id}"


@router.get(
    "/open",
    summary="Open an article",
    response_class=RedirectResponse,
    status_code=HTTPStatus.FOUND,
    responses={
        HTTPStatus.FOUND.value: {
            "description": "Redirect to the article.",
            "headers": {"Location": {"schema": {"type": "string"}}},
        },
        **problems.responses(HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND),
    },
)
def open_link(session: DbSession, article_id: ArticleId) -> RedirectResponse:
    """Redirects to the article and records its first open; later opens change nothing."""
    link = open_article(session, article_id, datetime.now(UTC))
    return RedirectResponse(link, status_code=HTTPStatus.FOUND, headers=NO_STORE)


@router.head("/open", include_in_schema=False)
def peek_link(session: DbSession, article_id: ArticleId) -> RedirectResponse:
    """The same redirect without recording, so link checkers and previews that
    only look do not count as reading."""
    link = article_link(session, article_id)
    return RedirectResponse(link, status_code=HTTPStatus.FOUND, headers=NO_STORE)
