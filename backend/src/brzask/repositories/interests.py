"""Interests: topics, keywords and reader notes."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from brzask.db.models import Interest


class InterestRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, interest_id: int) -> Interest | None:
        return self.session.get(Interest, interest_id)

    def get_by_topic(self, topic: str) -> Interest | None:
        query = select(Interest).where(Interest.topic == topic)
        return self.session.scalars(query).one_or_none()

    def find(self, *, active_only: bool = False) -> Sequence[Interest]:
        """Interests in the order they were added; prompts list them the same way."""
        query = select(Interest).order_by(Interest.id)
        if active_only:
            query = query.where(Interest.active)
        return self.session.scalars(query).all()

    def add(
        self, topic: str, *, keywords: Sequence[str] = (), notes: str = "", active: bool = True
    ) -> Interest:
        interest = Interest(topic=topic, keywords=list(keywords), notes=notes, active=active)
        self.session.add(interest)
        self.session.flush()
        return interest
