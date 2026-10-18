"""Interests and reader notes."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from brzask.db.models import ChangeStatus, Interest
from brzask.repositories import ChangeRepository, InterestRepository
from brzask.services.errors import ConflictError, NotFoundError, ServiceError


def find_interest(session: Session, ref: str) -> Interest:
    """An interest by ID or topic."""
    interests = InterestRepository(session)
    interest = interests.get(int(ref)) if ref.isdecimal() else interests.get_by_topic(ref)
    if interest is None:
        raise NotFoundError(f"no interest {ref!r}")
    return interest


def list_interests(session: Session, *, active_only: bool = False) -> Sequence[Interest]:
    return InterestRepository(session).find(active_only=active_only)


def add_interest(
    session: Session, topic: str, *, actor: str, keywords: Sequence[str] = (), notes: str = ""
) -> Interest:
    topic = _clean_topic(topic)
    interests = InterestRepository(session)
    if interests.get_by_topic(topic) is not None:
        raise ConflictError(f"interest {topic!r} already exists")
    interest = interests.add(topic, keywords=_clean_keywords(keywords), notes=notes.strip())
    ChangeRepository(session).record(
        actor=actor,
        action="interest.add",
        entity_type="interest",
        entity_id=str(interest.id),
        status=ChangeStatus.APPLIED,
        after=_snapshot(interest),
    )
    return interest


def edit_interest(
    session: Session,
    ref: str,
    *,
    actor: str,
    topic: str | None = None,
    keywords: Sequence[str] | None = None,
    notes: str | None = None,
    active: bool | None = None,
) -> Interest:
    """Change the given fields; the change log records only what changed."""
    interest = find_interest(session, ref)
    before = _snapshot(interest)
    if topic is not None:
        topic = _clean_topic(topic)
        other = InterestRepository(session).get_by_topic(topic)
        if other is not None and other.id != interest.id:
            raise ConflictError(f"interest {topic!r} already exists")
        interest.topic = topic
    if keywords is not None:
        interest.keywords = _clean_keywords(keywords)
    if notes is not None:
        interest.notes = notes.strip()
    if active is not None:
        interest.active = active
    after = _snapshot(interest)
    changed = {key for key in after if after[key] != before[key]}
    if changed:
        session.flush()
        ChangeRepository(session).record(
            actor=actor,
            action="interest.update",
            entity_type="interest",
            entity_id=str(interest.id),
            status=ChangeStatus.APPLIED,
            before={key: before[key] for key in changed},
            after={key: after[key] for key in changed},
        )
    return interest


def _clean_topic(topic: str) -> str:
    topic = topic.strip()
    if not topic:
        raise ServiceError("the topic must not be empty")
    return topic


def _clean_keywords(keywords: Sequence[str]) -> list[str]:
    """Trimmed, without blanks or repeats, in the given order."""
    return list(dict.fromkeys(keyword.strip() for keyword in keywords if keyword.strip()))


def _snapshot(interest: Interest) -> dict[str, Any]:
    return {
        "topic": interest.topic,
        "keywords": list(interest.keywords),
        "notes": interest.notes,
        "active": interest.active,
    }
