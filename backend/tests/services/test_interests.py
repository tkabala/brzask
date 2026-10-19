import pytest
from sqlalchemy.orm import Session

from brzask.repositories import ChangeRepository
from brzask.services.errors import ConflictError, NotFoundError, ServiceError
from brzask.services.interests import add_interest, edit_interest, find_interest
from tests.factories import Factories


def test_add_interest_cleans_input(session: Session) -> None:
    interest = add_interest(
        session, "  Rust ", actor="user", keywords=[" cargo", "", "rustc", "cargo"], notes=" x "
    )

    assert (interest.topic, interest.keywords, interest.notes) == ("Rust", ["cargo", "rustc"], "x")
    [change] = ChangeRepository(session).find(limit=5)
    assert change.action == "interest.add"
    assert change.after == {
        "topic": "Rust",
        "keywords": ["cargo", "rustc"],
        "notes": "x",
        "active": True,
    }


def test_add_interest_rejects_duplicates_and_blank_topics(
    session: Session, make: Factories
) -> None:
    make.interest("Rust")

    with pytest.raises(ConflictError):
        add_interest(session, "Rust", actor="user")
    with pytest.raises(ConflictError):
        add_interest(session, "rust", actor="user")
    with pytest.raises(ServiceError, match="empty"):
        add_interest(session, "  ", actor="user")


def test_edit_interest_logs_only_changed_fields(session: Session, make: Factories) -> None:
    interest = make.interest("AI", keywords=["llm"], notes="")

    edit_interest(
        session, "AI", actor="user", notes="skip: funding rounds", active=False, keywords=["llm"]
    )

    assert (interest.notes, interest.active) == ("skip: funding rounds", False)
    [change] = ChangeRepository(session).find(limit=5)
    assert change.before == {"notes": "", "active": True}
    assert change.after == {"notes": "skip: funding rounds", "active": False}


def test_edit_without_changes_logs_nothing(session: Session, make: Factories) -> None:
    interest = make.interest("AI")

    edit_interest(session, str(interest.id), actor="user", topic="AI")

    assert ChangeRepository(session).find(limit=5) == []


def test_edit_interest_rename_conflict(session: Session, make: Factories) -> None:
    make.interest("AI")
    make.interest("ML")

    with pytest.raises(ConflictError):
        edit_interest(session, "ML", actor="user", topic="AI")


def test_edit_interest_can_change_the_case_of_its_own_topic(
    session: Session, make: Factories
) -> None:
    interest = make.interest("Ai")

    edit_interest(session, "ai", actor="user", topic="AI")

    assert interest.topic == "AI"


def test_find_interest(session: Session, make: Factories) -> None:
    interest = make.interest("Postgres")

    assert find_interest(session, str(interest.id)) is interest
    assert find_interest(session, "Postgres") is interest
    with pytest.raises(NotFoundError):
        find_interest(session, "MySQL")
    with pytest.raises(NotFoundError):
        find_interest(session, "9" * 30)  # larger than any ID


def test_numeric_topics_are_rejected_since_they_read_as_ids(
    session: Session, make: Factories
) -> None:
    interest = make.interest("Postgres")

    with pytest.raises(ServiceError, match="cannot be a number"):
        add_interest(session, "2026", actor="user")
    with pytest.raises(ServiceError, match="cannot be a number"):
        edit_interest(session, str(interest.id), actor="user", topic=" 7 ")
