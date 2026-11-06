"""`/feed`: the digest of the last days as Atom, for feed readers.

Outside the versioned API, like `/open`: its URL lives in readers. Readers
send no session or header, so the URL carries a `feed` token, which opens
nothing else; each entry links through the signed `/open`, so reading from
the feed counts as an open.
"""

import hashlib
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response

from brzask.api import problems
from brzask.api.atom import FeedEntry, atom_feed
from brzask.api.auth import AuthConfig, public_origin
from brzask.api.deps import NO_NUL, DbSession
from brzask.api.problems import ProblemError
from brzask.config import get_settings
from brzask.db.models import TokenScope
from brzask.services import digests, tokens

router = APIRouter(tags=["digests"])

# A choice, not a measurement: a reader that polls once a week misses no day.
FEED_DAYS = 7
MEDIA_TYPE = "application/atom+xml; charset=utf-8"
# Readers poll; they must ask every time (the ETag makes that cheap), and no
# shared cache may keep a document reached with a token.
CACHE_CONTROL = "private, no-cache"
# An empty feed's `updated`: a fixed date, so its ETag holds between polls.
NO_ENTRIES = datetime.fromtimestamp(0, UTC)

FeedToken = Annotated[
    str | None,
    Query(
        max_length=200,
        pattern=NO_NUL,
        description="A feed token from `brzask tokens create --scope feed`.",
    ),
]


@router.get(
    "/feed",
    summary="The digest as an Atom feed",
    response_class=Response,
    responses={
        HTTPStatus.OK.value: {
            "description": "Atom feed of the last days' digests, newest first.",
            "content": {"application/atom+xml": {}},
        },
        HTTPStatus.NOT_MODIFIED.value: {"description": "Unchanged since the given ETag."},
        **problems.responses(HTTPStatus.BAD_REQUEST, HTTPStatus.UNAUTHORIZED),
    },
)
def get_feed(
    request: Request,
    session: DbSession,
    config: AuthConfig,
    token: FeedToken = None,
    if_none_match: Annotated[str | None, Header(max_length=1000)] = None,
) -> Response:
    """The last seven days with a digest, each article linking through `/open`."""
    if config.mode != "none" and not _feed_token(session, token):
        raise ProblemError(
            HTTPStatus.UNAUTHORIZED,
            "Add ?token= with a token from 'brzask tokens create --scope feed'.",
        )
    origin = public_origin(request, config)
    entries = [
        FeedEntry(
            id=f"urn:brzask:article:{article.id}",
            title=article.digest_title or article.title,
            link=origin + config.open_url(article.id),
            summary=article.summary,
            why_it_matters=article.why_it_matters,
            topic=article.topic,
            source=article.source.name if article.source else None,
            published=article.shown_at or article.first_seen_at,
        )
        for day in digests.recent_digests(session, FEED_DAYS)
        for article in day.articles
    ]
    updated = max((e.published for e in entries), default=NO_ENTRIES)
    body = atom_feed(
        entries,
        base=origin + config.root_path,
        language=get_settings().digest.language,
        updated=updated,
    )
    etag = f'"{hashlib.sha256(body).hexdigest()[:32]}"'
    headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
    if if_none_match is not None and etag in _etags(if_none_match):
        return Response(status_code=HTTPStatus.NOT_MODIFIED, headers=headers)
    return Response(body, media_type=MEDIA_TYPE, headers=headers)


def _feed_token(session: DbSession, value: str | None) -> bool:
    if value is None:
        return False
    token = tokens.authenticate_token(session, value, datetime.now(UTC))
    return token is not None and token.scope is TokenScope.FEED


def _etags(header: str) -> set[str]:
    """The tags in If-None-Match; weak ones compare equal (RFC 9110, 13.1.2)."""
    return {tag.strip().removeprefix("W/") for tag in header.split(",")}
