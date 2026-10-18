from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from brzask.db.models import Source, SourceOrigin, SourceStatus
from brzask.db.session import session_factory
from tests.factories import Factories


def count_sources(engine: Engine) -> int:
    with Session(engine) as other:
        return other.scalar(select(func.count()).select_from(Source)) or 0


def test_commits_in_a_test_never_reach_the_database(
    session: Session, make: Factories, db_engine: Engine
) -> None:
    make.source()
    session.commit()

    assert session.scalar(select(func.count()).select_from(Source)) == 1
    assert count_sources(db_engine) == 0


def test_session_factory_keeps_objects_readable_after_commit(db_engine: Engine) -> None:
    factory = session_factory(db_engine)
    with factory.begin() as session:
        source = Source(
            name="Committed",
            url="https://committed.example/feed",
            status=SourceStatus.ACTIVE,
            origin=SourceOrigin.MANUAL,
        )
        session.add(source)
    try:
        assert source.name == "Committed"
        assert count_sources(db_engine) == 1
    finally:
        with factory.begin() as session:
            session.delete(session.merge(source))
