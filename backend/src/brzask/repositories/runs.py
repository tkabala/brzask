"""Pipeline runs."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
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

    def latest(self, kind: RunKind) -> Run | None:
        return next(iter(self.recent(1, kind)), None)
