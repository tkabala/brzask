from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from brzask.db.models import Change, TokenScope
from brzask.services import tokens
from brzask.services.auth import TOUCH_INTERVAL, token_hash
from brzask.services.errors import ConflictError, NotFoundError, ServiceError

NOW = datetime(2026, 10, 21, 9, tzinfo=UTC)


def test_create_stores_only_a_hash(session: Session) -> None:
    token, value = tokens.create_token(session, " ci ", TokenScope.WRITE, actor="user")

    assert value.startswith("brz_") and len(value) > 40
    assert token.name == "ci"
    assert token.prefix == value[:12]
    assert token.token_hash == token_hash(value)
    assert value not in (token.prefix, token.token_hash)
    change = session.scalars(select(Change)).one()
    assert (change.action, change.after) == ("token.create", {"name": "ci", "scope": "write"})


def test_names_are_unique_and_not_blank(session: Session) -> None:
    tokens.create_token(session, "ci", TokenScope.READ, actor="user")

    with pytest.raises(ConflictError):
        tokens.create_token(session, "ci", TokenScope.WRITE, actor="user")
    with pytest.raises(ServiceError):
        tokens.create_token(session, "  ", TokenScope.READ, actor="user")


def test_authenticate_and_revoke(session: Session) -> None:
    _, value = tokens.create_token(session, "ci", TokenScope.READ, actor="user")

    token = tokens.authenticate_token(session, value, NOW)
    assert token is not None and token.last_used_at == NOW
    assert tokens.authenticate_token(session, value + "x", NOW) is None

    assert tokens.revoke_token(session, "ci", NOW, actor="user")
    assert not tokens.revoke_token(session, "ci", NOW, actor="user")
    assert tokens.authenticate_token(session, value, NOW) is None
    with pytest.raises(NotFoundError):
        tokens.revoke_token(session, "nope", NOW, actor="user")


def test_last_use_is_written_now_and_then(session: Session) -> None:
    _, value = tokens.create_token(session, "ci", TokenScope.READ, actor="user")
    tokens.authenticate_token(session, value, NOW)

    soon = tokens.authenticate_token(session, value, NOW + timedelta(minutes=5))
    assert soon is not None and soon.last_used_at == NOW
    later = tokens.authenticate_token(session, value, NOW + TOUCH_INTERVAL)
    assert later is not None and later.last_used_at == NOW + TOUCH_INTERVAL
