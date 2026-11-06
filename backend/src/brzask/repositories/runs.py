"""Pipeline runs."""

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Numeric, and_, case, cast, func, or_, select, tuple_
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

    def earlier_digest_on(self, day: date, run: Run) -> bool:
        """Whether a real digest run for `day` finished ok before `run` started."""
        query = select(Run.id).where(
            Run.kind == RunKind.DIGEST,
            Run.status == RunStatus.OK,
            Run.dry_run.is_(False),
            Run.stats["date"].astext == day.isoformat(),
            Run.id != run.id,
            Run.started_at <= run.started_at,
        )
        return self.session.scalars(query.limit(1)).first() is not None

    def latest(self, kind: RunKind) -> Run | None:
        return next(iter(self.recent(1, kind)), None)

    def spending(self, day_start: datetime, month_start: datetime) -> tuple[Decimal, Decimal, int]:
        """Reported cost of the runs since `day_start` and since `month_start`.

        Also the number of runs since `month_start` with calls that reported no
        cost, which make the sums a lower bound. Runs recorded before usage
        had `cost_usd_known` count their `cost_usd`, unpriced when it is null.
        """
        usage = Run.stats["usage"]

        def number(key: str) -> ColumnElement[Decimal]:
            # Only JSON numbers are cast: one odd value must not fail every run's check.
            value = usage[key]
            return case((func.jsonb_typeof(value) == "number", cast(value.astext, Numeric)))

        cost = func.coalesce(number("cost_usd_known"), number("cost_usd"), 0)
        unpriced = or_(
            number("unpriced_calls") > 0,
            and_(
                ~usage.has_key("cost_usd_known"),
                number("calls") > 0,
                func.jsonb_typeof(usage["cost_usd"]) == "null",
            ),
        )
        query = select(
            func.coalesce(func.sum(cost).filter(Run.started_at >= day_start), 0),
            func.coalesce(func.sum(cost), 0),
            func.count().filter(unpriced),
        ).where(Run.started_at >= month_start)
        today, month, unpriced_runs = self.session.execute(query).one()
        return Decimal(today), Decimal(month), int(unpriced_runs)
