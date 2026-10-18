from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from brzask.repositories import ChangeRepository
from brzask.services.errors import ServiceError
from brzask.services.pause import pause, paused_until, resume

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)


def test_pause_until_a_moment(session: Session) -> None:
    until = NOW + timedelta(days=3)

    pause(session, until, NOW, actor="user")

    assert paused_until(session, NOW) == until
    assert paused_until(session, until) is None  # over once the moment comes
    [change] = ChangeRepository(session).find(limit=5)
    assert (change.action, change.before, change.after) == (
        "digest.pause",
        None,
        {"until": until.isoformat()},
    )


def test_pause_must_end_in_the_future_with_a_time_zone(session: Session) -> None:
    with pytest.raises(ServiceError, match="not in the future"):
        pause(session, NOW, NOW, actor="user")
    with pytest.raises(ServiceError, match="time zone"):
        pause(session, datetime(2026, 10, 20), NOW, actor="user")


def test_resume(session: Session) -> None:
    assert not resume(session, NOW, actor="user")

    pause(session, NOW + timedelta(days=1), NOW, actor="user")

    assert resume(session, NOW, actor="user")
    assert paused_until(session, NOW) is None
    assert ChangeRepository(session).find(limit=1)[0].action == "digest.resume"


def test_an_expired_pause_is_not_resumed(session: Session) -> None:
    pause(session, NOW + timedelta(hours=1), NOW, actor="user")

    assert not resume(session, NOW + timedelta(hours=2), actor="user")
