"""Spending limits: what the recorded runs cost today and this month.

Spending is the cost providers report for paid calls (LLM, embeddings, judge,
web search), summed over every recorded run, forced and dry runs included.
A pipeline checks it once, when it starts: a run started under the limit runs
in full, so one run can take spending past the limit by its own cost. Calls
without a reported cost count as nothing, and the spending says how many runs
had them. Days and months are local to the scheduler's time zone, like the
digest date.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, tzinfo
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from brzask.config.settings import BudgetSettings
from brzask.repositories import RunRepository


@dataclass(frozen=True, slots=True)
class Spending:
    today: Decimal
    month: Decimal
    unpriced_runs: int  # runs this month with calls that reported no cost


@dataclass(frozen=True, slots=True)
class BudgetState:
    daily: Decimal | None
    monthly: Decimal | None
    spending: Spending
    reason: str | None  # why a limit is reached; None when under every limit

    @property
    def over(self) -> bool:
        return self.reason is not None

    def stats(self, skipped: Sequence[str]) -> dict[str, Any]:
        """For the run stats, with the steps the run left out because of it."""
        return {
            "daily_usd": _number(self.daily),
            "monthly_usd": _number(self.monthly),
            "spent_today": _number(self.spending.today),
            "spent_month": _number(self.spending.month),
            "unpriced_runs": self.spending.unpriced_runs,
            "over": self.over,
            "reason": self.reason,
            "skipped": list(skipped),
        }


def window_starts(now: datetime, tz: tzinfo) -> tuple[datetime, datetime]:
    """Start of the local day and of the local month around `now`, in UTC."""
    today = now.astimezone(tz).date()
    # Built from the date, each start gets its own offset (the month may begin in summer time).
    return (
        datetime.combine(today, time(), tzinfo=tz).astimezone(UTC),
        datetime.combine(today.replace(day=1), time(), tzinfo=tz).astimezone(UTC),
    )


def evaluate(settings: BudgetSettings, spending: Spending) -> BudgetState:
    """Whether a limit is reached; the daily one is named first."""
    reason = None
    if settings.daily_usd is not None and spending.today >= settings.daily_usd:
        reason = (
            f"daily LLM budget ${_limit(settings.daily_usd)} reached "
            f"(${spending.today:.4f} spent today)"
        )
    elif settings.monthly_usd is not None and spending.month >= settings.monthly_usd:
        reason = (
            f"monthly LLM budget ${_limit(settings.monthly_usd)} reached "
            f"(${spending.month:.4f} spent this month)"
        )
    return BudgetState(settings.daily_usd, settings.monthly_usd, spending, reason)


def check_budget(
    session: Session, now: datetime, settings: BudgetSettings, tz: tzinfo
) -> BudgetState | None:
    """The budget at `now`, or None when no limit is set."""
    if settings.daily_usd is None and settings.monthly_usd is None:
        return None
    day_start, month_start = window_starts(now, tz)
    today, month, unpriced = RunRepository(session).spending(day_start, month_start)
    return evaluate(settings, Spending(today, month, unpriced))


def agent_runs_today(session: Session, now: datetime, tz: tzinfo) -> int:
    """Runs agents started since local midnight, skipped and failed ones included."""
    return RunRepository(session).started_by_agents_since(window_starts(now, tz)[0])


def _limit(value: Decimal) -> str:
    """A limit as written, without trailing zeros: 0.05, 1, 20."""
    return f"{value.normalize():f}"


def _number(value: Decimal | None) -> float | None:
    return None if value is None else round(float(value), 6)
