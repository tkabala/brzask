"""Spending limits: the windows, the decision and its stats."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from brzask.config.settings import BudgetSettings
from brzask.db.models import RunStatus
from brzask.services.budget import (
    Spending,
    agent_runs_today,
    check_budget,
    evaluate,
    window_starts,
)
from tests.factories import Factories

WARSAW = ZoneInfo("Europe/Warsaw")


def spending(today: str, month: str, unpriced: int = 0) -> Spending:
    return Spending(Decimal(today), Decimal(month), unpriced)


def limits(daily: str | None = None, monthly: str | None = None) -> BudgetSettings:
    return BudgetSettings(
        daily_usd=Decimal(daily) if daily else None,
        monthly_usd=Decimal(monthly) if monthly else None,
    )


def test_window_starts_are_local_midnight_and_the_first() -> None:
    # 23:30 CET on 31 October; the month began in summer time (CEST).
    now = datetime(2026, 10, 31, 22, 30, tzinfo=UTC)

    day_start, month_start = window_starts(now, WARSAW)

    assert day_start == datetime(2026, 10, 30, 23, tzinfo=UTC)
    assert month_start == datetime(2026, 9, 30, 22, tzinfo=UTC)


def test_under_the_limits_is_not_over() -> None:
    state = evaluate(limits("0.05", "1"), spending("0.0499", "0.5"))

    assert not state.over
    assert state.reason is None


def test_reaching_the_daily_limit_is_over() -> None:
    state = evaluate(limits("0.05"), spending("0.05", "0.05"))

    assert state.over
    assert state.reason == "daily LLM budget $0.05 reached ($0.0500 spent today)"


def test_monthly_limit() -> None:
    state = evaluate(limits(monthly="1.00"), spending("0.01", "1.02"))

    assert state.reason == "monthly LLM budget $1 reached ($1.0200 spent this month)"


def test_daily_reason_comes_first_when_both_are_reached() -> None:
    state = evaluate(limits("0.05", "1"), spending("0.06", "1.5"))

    assert state.reason is not None
    assert state.reason.startswith("daily")


def test_stats_are_json_floats() -> None:
    state = evaluate(limits("0.05"), spending("0.0531", "0.4", unpriced=2))

    stats = state.stats(["ranking"])

    json.dumps(stats)
    assert stats == {
        "daily_usd": 0.05,
        "monthly_usd": None,
        "spent_today": 0.0531,
        "spent_month": 0.4,
        "unpriced_runs": 2,
        "over": True,
        "reason": "daily LLM budget $0.05 reached ($0.0531 spent today)",
        "skipped": ["ranking"],
    }


def test_no_limits_means_no_budget(session: Session) -> None:
    assert check_budget(session, datetime.now(UTC), limits(), WARSAW) is None


def test_check_budget_counts_a_run_late_on_the_last_day_of_the_month(
    session: Session, make: Factories
) -> None:
    make.run(datetime(2026, 10, 31, 22, 30, tzinfo=UTC), cost=0.02)  # 23:30 local

    late = check_budget(session, datetime(2026, 10, 31, 22, 45, tzinfo=UTC), limits("0.01"), WARSAW)
    # 00:05 on 1 November in Warsaw, still 31 October in UTC.
    next_day = check_budget(
        session, datetime(2026, 10, 31, 23, 5, tzinfo=UTC), limits("0.01"), WARSAW
    )

    assert late is not None and late.over
    assert next_day is not None and not next_day.over
    assert next_day.spending.month == 0


def test_agent_runs_today_counts_local_days_and_agents_only(
    session: Session, make: Factories
) -> None:
    now = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)  # 10:00 in Warsaw
    make.run(datetime(2026, 11, 12, 23, 30, tzinfo=UTC), started_by="agent:a")  # 00:30 local
    make.run(
        datetime(2026, 11, 13, 8, 0, tzinfo=UTC), started_by="agent:b", status=RunStatus.SKIPPED
    )
    make.run(datetime(2026, 11, 13, 8, 30, tzinfo=UTC))  # the scheduler
    make.run(datetime(2026, 11, 12, 22, 30, tzinfo=UTC), started_by="agent:a")  # 23:30 yesterday

    assert agent_runs_today(session, now, WARSAW) == 2
