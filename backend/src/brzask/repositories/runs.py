"""Pipeline runs."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from brzask.db.models import Run, RunKind, RunStatus


class RunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, run_id: uuid.UUID) -> Run | None:
        return self.session.get(Run, run_id)

    def start(
        self, run_id: uuid.UUID, kind: RunKind, started_at: datetime, *, dry_run: bool = False
    ) -> Run:
        run = Run(id=run_id, kind=kind, started_at=started_at, dry_run=dry_run)
        self.session.add(run)
        self.session.flush()
        return run

    def finish(
        self,
        run: Run,
        status: RunStatus,
        finished_at: datetime,
        *,
        stats: dict[str, Any] | None = None,
        timings: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        run.status = status
        run.finished_at = finished_at
        run.stats = stats or {}
        run.timings = timings or {}
        run.error = error
        self.session.flush()

    def recent(self, limit: int, kind: RunKind | None = None) -> Sequence[Run]:
        """Newest runs first, of every kind or only `kind`."""
        query = select(Run).order_by(Run.started_at.desc()).limit(limit)
        if kind is not None:
            query = query.where(Run.kind == kind)
        return self.session.scalars(query).all()

    def page(
        self,
        limit: int,
        *,
        kind: RunKind | None = None,
        after: tuple[datetime, uuid.UUID] | None = None,
    ) -> Sequence[Run]:
        """Up to `limit` runs, newest first, that come after the (started_at, id) key `after`."""
        query = select(Run).order_by(Run.started_at.desc(), Run.id.desc()).limit(limit)
        if kind is not None:
            query = query.where(Run.kind == kind)
        if after is not None:
            query = query.where(tuple_(Run.started_at, Run.id) < tuple_(*after))
        return self.session.scalars(query).all()

    def digest_started_at(self, started_at: datetime) -> Run | None:
        """The digest run (not a dry run) that started at `started_at`.

        A digest's articles are marked shown with the start of their run.
        """
        query = select(Run).where(
            Run.kind == RunKind.DIGEST, Run.dry_run.is_(False), Run.started_at == started_at
        )
        return self.session.scalars(query.limit(1)).first()

    def latest(self, kind: RunKind) -> Run | None:
        return next(iter(self.recent(1, kind)), None)
