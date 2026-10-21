"""`/open`: follow an article's link and record the open.

Outside the versioned API, as its URLs end up in feed readers, mail and
bookmarks and must keep working.
"""

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from brzask.api import problems
from brzask.api.auth import AuthConfig, SessionCookie, identify
from brzask.api.deps import MAX_API_ID, NO_NUL, DbSession
from brzask.api.problems import ProblemError
from brzask.services import auth
from brzask.services.opens import article_link, open_article

router = APIRouter(tags=["articles"])

ArticleId = Annotated[int, Query(alias="id", ge=1, le=MAX_API_ID, description="Article ID.")]

Signature = Annotated[
    str | None,
    Query(max_length=64, pattern=NO_NUL, description="From the article's `open_url`."),
]

# Every open must reach the server; a cached redirect would skip recording it.
NO_STORE = {"Cache-Control": "no-store"}


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
        **problems.responses(HTTPStatus.BAD_REQUEST, HTTPStatus.UNAUTHORIZED, HTTPStatus.NOT_FOUND),
    },
)
def open_link(
    request: Request,
    session: DbSession,
    config: AuthConfig,
    token: SessionCookie,
    article_id: ArticleId,
    sig: Signature = None,
) -> RedirectResponse:
    """Redirects to the article and records its first open; later opens change nothing.

    Works with the signature from the article's `open_url` or with a session.
    """
    _check_access(request, session, config, token, article_id, sig)
    link = open_article(session, article_id, datetime.now(UTC))
    return RedirectResponse(link, status_code=HTTPStatus.FOUND, headers=NO_STORE)


@router.head("/open", include_in_schema=False)
def peek_link(
    request: Request,
    session: DbSession,
    config: AuthConfig,
    token: SessionCookie,
    article_id: ArticleId,
    sig: Signature = None,
) -> RedirectResponse:
    """The same redirect without recording, so link checkers and previews that
    only look do not count as reading."""
    _check_access(request, session, config, token, article_id, sig)
    link = article_link(session, article_id)
    return RedirectResponse(link, status_code=HTTPStatus.FOUND, headers=NO_STORE)


def _check_access(
    request: Request,
    session: DbSession,
    config: AuthConfig,
    token: str | None,
    article_id: int,
    sig: str | None,
) -> None:
    """Links are opened from feed readers and mail, which send no session: a
    valid signature is enough, and an authenticated request works without one."""
    if config.mode == "none":
        return
    if auth.link_signature_matches(config.signing_secret(), article_id, sig):
        return
    if identify(request, session, config, token) is not None:
        return
    raise ProblemError(HTTPStatus.UNAUTHORIZED, "This link is not signed; log in to open it.")
