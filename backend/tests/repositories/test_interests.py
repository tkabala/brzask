import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from brzask.repositories import InterestRepository
from tests.factories import Factories


def test_add_stores_keywords_and_notes(session: Session) -> None:
    interests = InterestRepository(session)

    interest = interests.add("Rust", keywords=["cargo", "rustc"], notes="skip: crate releases")
    session.expire_all()

    stored = interests.get(interest.id)
    assert stored is not None
    assert stored.keywords == ["cargo", "rustc"]
    assert stored.notes == "skip: crate releases"
    assert stored.active


def test_find_keeps_insertion_order_and_filters_active(session: Session, make: Factories) -> None:
    make.interest("Zig")
    make.interest("AI", active=False)
    make.interest("Databases")
    interests = InterestRepository(session)

    assert [i.topic for i in interests.find()] == ["Zig", "AI", "Databases"]
    assert [i.topic for i in interests.find(active_only=True)] == ["Zig", "Databases"]


def test_get_by_topic(session: Session, make: Factories) -> None:
    interest = make.interest("Postgres")
    interests = InterestRepository(session)

    assert interests.get_by_topic("Postgres") is interest
    assert interests.get_by_topic("postgres") is interest
    assert interests.get_by_topic("MySQL") is None


def test_topics_are_unique_ignoring_case(session: Session, make: Factories) -> None:
    make.interest("Postgres")

    with pytest.raises(IntegrityError, match="uq_interests_lower_topic"):
        make.interest("postgres")
