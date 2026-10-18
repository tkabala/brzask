from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from brzask.db.models import TokenScope
from brzask.repositories import ApiTokenRepository

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)


def test_add_and_find_by_hash(session: Session) -> None:
    tokens = ApiTokenRepository(session)

    token = tokens.add(name="agent", prefix="bz_abc", token_hash="h1", scope=TokenScope.WRITE)

    assert tokens.find_usable("h1") is token
    assert tokens.find_usable("unknown") is None
    assert tokens.get_by_name("agent") is token


def test_revoked_tokens_are_not_usable(session: Session) -> None:
    tokens = ApiTokenRepository(session)
    token = tokens.add(name="agent", prefix="bz_abc", token_hash="h1", scope=TokenScope.READ)

    tokens.revoke(token, NOW)
    tokens.revoke(token, NOW + timedelta(days=1))

    assert token.revoked_at == NOW
    assert tokens.find_usable("h1") is None


def test_touch_and_list_by_name(session: Session) -> None:
    tokens = ApiTokenRepository(session)
    second = tokens.add(name="zeta", prefix="bz_z", token_hash="h2", scope=TokenScope.READ)
    first = tokens.add(name="alpha", prefix="bz_a", token_hash="h1", scope=TokenScope.READ)

    tokens.touch(first, NOW)

    assert first.last_used_at == NOW
    assert list(tokens.find()) == [first, second]
