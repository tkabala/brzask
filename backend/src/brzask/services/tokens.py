"""API tokens for scripts and agents: created, listed and revoked from the command line.

A token is shown once, when it is created; only its SHA-256 is stored, with
its first characters to tell tokens apart. A `read` token may only read; a
`write` token may also change things.
"""

import secrets
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.orm import Session

from brzask.db.models import ApiToken, ChangeStatus, TokenScope
from brzask.repositories import ApiTokenRepository, ChangeRepository
from brzask.services.auth import TOUCH_INTERVAL, token_hash
from brzask.services.errors import ConflictError, NotFoundError, ServiceError

# Marks brzask tokens, so secret scanners and people recognise them.
TOKEN_PREFIX = "brz_"  # noqa: S105 (a marker, not a secret)
# Characters kept in the clear: the marker and the first 8 random ones.
SHOWN_CHARS = len(TOKEN_PREFIX) + 8
MAX_NAME = 100


def create_token(
    session: Session, name: str, scope: TokenScope, *, actor: str
) -> tuple[ApiToken, str]:
    """A new token and its value, which is not stored and cannot be shown again."""
    name = name.strip()
    if not name or len(name) > MAX_NAME:
        raise ServiceError(f"a token name needs 1 to {MAX_NAME} characters")
    tokens = ApiTokenRepository(session)
    if tokens.get_by_name(name) is not None:
        raise ConflictError(f"a token named {name!r} already exists")
    value = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = tokens.add(
        name=name, prefix=value[:SHOWN_CHARS], token_hash=token_hash(value), scope=scope
    )
    ChangeRepository(session).record(
        actor=actor,
        action="token.create",
        entity_type="api_token",
        entity_id=str(token.id),
        status=ChangeStatus.APPLIED,
        after={"name": name, "scope": scope.value},
    )
    return token, value


def list_tokens(session: Session) -> Sequence[ApiToken]:
    """Every token by name, revoked ones included."""
    return ApiTokenRepository(session).find()


def revoke_token(session: Session, name: str, now: datetime, *, actor: str) -> bool:
    """Stop a token from working. False when it was already revoked."""
    tokens = ApiTokenRepository(session)
    token = tokens.get_by_name(name)
    if token is None:
        raise NotFoundError(f"no token {name!r}")
    if token.revoked_at is not None:
        return False
    tokens.revoke(token, now)
    ChangeRepository(session).record(
        actor=actor,
        action="token.revoke",
        entity_type="api_token",
        entity_id=str(token.id),
        status=ChangeStatus.APPLIED,
        before={"name": name, "scope": token.scope.value},
    )
    return True


def authenticate_token(session: Session, value: str, now: datetime) -> ApiToken | None:
    """The usable token with this value, its last use updated now and then."""
    tokens = ApiTokenRepository(session)
    token = tokens.find_usable(token_hash(value))
    if token is not None and (
        token.last_used_at is None or now - token.last_used_at >= TOUCH_INTERVAL
    ):
        tokens.touch(token, now)
    return token
