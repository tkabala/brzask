import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.orm import Session

from brzask.db.models import DeepDive, DeepDiveStatus

ACTIVE = (DeepDiveStatus.QUEUED, DeepDiveStatus.RUNNING)
INTERRUPTED = "interrupted"


class DuplicateDeepDiveError(Exception):
    """The same article and focus are already queued or being written."""


class DeepDiveRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, article_id: int, focus: str) -> DeepDive:
        """A queued dive; refused while one with the same article and focus is active.

        Foci are compared trimmed and case-insensitively, so a double tap or a
        second tab asks once.
        """
        focus = focus.strip()
        active = self.session.scalars(
            select(DeepDive.focus).where(
                DeepDive.article_id == article_id, DeepDive.status.in_(ACTIVE)
            )
        )
        if any(other.strip().casefold() == focus.casefold() for other in active):
            raise DuplicateDeepDiveError(focus)
        dive = DeepDive(article_id=article_id, focus=focus, status=DeepDiveStatus.QUEUED)
        self.session.add(dive)
        self.session.flush()
        return dive

    def get(self, dive_id: int) -> DeepDive | None:
        return self.session.get(DeepDive, dive_id)

    def for_article(self, article_id: int) -> Sequence[DeepDive]:
        """The article's dives, newest first."""
        return self.session.scalars(
            select(DeepDive)
            .where(DeepDive.article_id == article_id)
            .order_by(DeepDive.created_at.desc(), DeepDive.id.desc())
        ).all()

    def page(self, limit: int, before: tuple[datetime, int] | None) -> Sequence[DeepDive]:
        """Dives newest first; after the dive with `before` = (created_at, id) when given."""
        query = select(DeepDive).order_by(DeepDive.created_at.desc(), DeepDive.id.desc())
        if before is not None:
            query = query.where(tuple_(DeepDive.created_at, DeepDive.id) < tuple_(*before))
        return self.session.scalars(query.limit(limit)).all()

    def counts(self) -> tuple[int, int]:
        """(unread, active): finished and not opened yet; queued or running."""
        unread, active = self.session.execute(
            select(
                func.count().filter(
                    DeepDive.status == DeepDiveStatus.DONE, DeepDive.read_at.is_(None)
                ),
                func.count().filter(DeepDive.status.in_(ACTIVE)),
            )
        ).one()
        return unread, active

    def start(self, dive_id: int, run_id: uuid.UUID) -> None:
        self._set(dive_id, status=DeepDiveStatus.RUNNING, run_id=run_id)

    def finish(
        self,
        dive_id: int,
        *,
        report: dict[str, Any],
        sources: list[dict[str, Any]],
        thin: bool,
        searched_web: bool,
        model: str,
        at: datetime,
    ) -> None:
        self._set(
            dive_id,
            status=DeepDiveStatus.DONE,
            report=report,
            sources=sources,
            thin=thin,
            searched_web=searched_web,
            model=model,
            error=None,
            finished_at=at,
        )

    def fail(self, dive_id: int, error: str, at: datetime) -> None:
        self._set(dive_id, status=DeepDiveStatus.FAILED, error=error, finished_at=at)

    def mark_read(self, dive_id: int, at: datetime) -> bool:
        """Record the first time the dive was opened; False when there is no such dive."""
        dive = self.get(dive_id)
        if dive is None:
            return False
        if dive.read_at is None:
            dive.read_at = at
            self.session.flush()
        return True

    def fail_interrupted(self, at: datetime) -> int:
        """Fail every queued or running dive (the process writing them stopped)."""
        result = self.session.execute(
            update(DeepDive)
            .where(DeepDive.status.in_(ACTIVE))
            .values(status=DeepDiveStatus.FAILED, error=INTERRUPTED, finished_at=at)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount)  # type: ignore[attr-defined]

    def _set(self, dive_id: int, **values: Any) -> None:
        dive = self.get(dive_id)
        if dive is None:
            raise LookupError(f"no deep dive {dive_id}")
        for name, value in values.items():
            setattr(dive, name, value)
        self.session.flush()
