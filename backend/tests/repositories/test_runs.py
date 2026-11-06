import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from brzask.db.models import RunKind, RunStatus
from brzask.repositories import RunRepository
from tests.factories import Factories

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)


def test_start_and_finish(session: Session) -> None:
    runs = RunRepository(session)
    run_id = uuid.uuid4()

    run = runs.start(run_id, RunKind.DIGEST, NOW, dry_run=True)
    assert run.status is RunStatus.RUNNING

    runs.finish(
        run,
        RunStatus.OK,
        NOW + timedelta(minutes=2),
        stats={"selected": 7},
        timings={"ranking": 12000},
    )
    session.expire_all()

    stored = runs.get(run_id)
    assert stored is not None
    assert stored.dry_run
    assert (stored.status, stored.stats, stored.timings) == (
        RunStatus.OK,
        {"selected": 7},
        {"ranking": 12000},
    )
    assert stored.finished_at == NOW + timedelta(minutes=2)


def test_finish_with_an_error(session: Session) -> None:
    runs = RunRepository(session)
    run = runs.start(uuid.uuid4(), RunKind.REVIEW, NOW)

    runs.finish(run, RunStatus.FAILED, NOW, error="RuntimeError: no sources")

    assert (run.status, run.error, run.stats) == (RunStatus.FAILED, "RuntimeError: no sources", {})


def test_recent_and_latest(session: Session) -> None:
    runs = RunRepository(session)
    old_digest = runs.start(uuid.uuid4(), RunKind.DIGEST, NOW - timedelta(days=1))
    review = runs.start(uuid.uuid4(), RunKind.REVIEW, NOW - timedelta(hours=1))
    digest = runs.start(uuid.uuid4(), RunKind.DIGEST, NOW)

    assert list(runs.recent(10)) == [digest, review, old_digest]
    assert list(runs.recent(10, RunKind.DIGEST)) == [digest, old_digest]
    assert runs.latest(RunKind.REVIEW) is review
    assert runs.latest(RunKind.DISCOVERY) is None


def test_spending_sums_runs_by_window(session: Session, make: Factories) -> None:
    day_start = datetime(2026, 10, 17, 22, tzinfo=UTC)
    month_start = datetime(2026, 9, 30, 22, tzinfo=UTC)
    make.run(month_start - timedelta(minutes=1), cost=1.0)  # last month
    make.run(month_start, cost=0.1)
    make.run(day_start - timedelta(minutes=1), cost=0.02)
    make.run(day_start, cost=0.003)
    make.run(NOW, cost=0.05, kind=RunKind.DISCOVERY)
    make.run(NOW, stats={})  # no paid calls

    today, month, unpriced = RunRepository(session).spending(day_start, month_start)

    assert (today, month, unpriced) == (Decimal("0.053"), Decimal("0.173"), 0)


def test_spending_counts_legacy_and_unpriced_runs(session: Session, make: Factories) -> None:
    make.run(NOW, stats={"usage": {"calls": 2, "cost_usd": 0.01}})  # before cost_usd_known
    make.run(NOW, stats={"usage": {"calls": 1, "cost_usd": None}})
    make.run(
        NOW,
        stats={
            "usage": {"calls": 3, "cost_usd": None, "cost_usd_known": 0.002, "unpriced_calls": 1}
        },
    )

    today, month, unpriced = RunRepository(session).spending(NOW, NOW)

    assert (today, month, unpriced) == (Decimal("0.012"), Decimal("0.012"), 2)


def test_spending_ignores_values_that_are_not_numbers(session: Session, make: Factories) -> None:
    make.run(NOW, stats={"usage": {"calls": 1, "cost_usd": "n/a"}})
    make.run(NOW, stats={"usage": {"cost_usd_known": "0.5", "unpriced_calls": "1.5"}})
    make.run(NOW, stats={"usage": [1, 2]})
    make.run(NOW, cost=0.01)

    today, month, unpriced = RunRepository(session).spending(NOW, NOW)

    assert (today, month, unpriced) == (Decimal("0.01"), Decimal("0.01"), 0)


def test_earlier_digest_on_counts_only_earlier_real_digests(make: Factories) -> None:
    runs = RunRepository(make.session)
    day = {"date": "2026-10-18"}
    make.run(NOW - timedelta(hours=1), stats=day, dry_run=True)
    make.run(NOW - timedelta(minutes=50), stats=day, status=RunStatus.FAILED)
    make.run(NOW - timedelta(minutes=40), stats={"date": "2026-10-17"})
    make.run(NOW - timedelta(minutes=30), stats=day, kind=RunKind.REVIEW)
    first = make.run(NOW, stats=day)
    second = make.run(NOW + timedelta(minutes=5), stats=day)

    assert runs.earlier_digest_on(date(2026, 10, 18), first) is False
    assert runs.earlier_digest_on(date(2026, 10, 18), second) is True
