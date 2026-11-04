from datetime import date

from sqlalchemy.orm import Session

from brzask.services.digests import recent_digests
from tests.factories import Factories


def test_recent_digests_newest_day_first(session: Session, make: Factories) -> None:
    for day in (date(2026, 11, 1), date(2026, 11, 3), date(2026, 11, 2)):
        make.article(digest_date=day)
        make.article(digest_date=day)
    make.article()  # never shown
    session.flush()

    result = recent_digests(session, 2)

    assert [d.day for d in result] == [date(2026, 11, 3), date(2026, 11, 2)]
    assert [a.digest_position for a in result[0].articles] == [1, 2]
    assert all(a.digest_date == date(2026, 11, 3) for a in result[0].articles)


def test_recent_digests_without_any(session: Session) -> None:
    assert recent_digests(session, 7) == []
