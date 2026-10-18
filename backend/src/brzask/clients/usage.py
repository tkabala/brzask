"""Token and cost accounting for calls to paid APIs, summed per run."""

import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CallUsage:
    model: str
    purpose: str  # what the call was for, e.g. "ranking"; totals are grouped by it
    input_tokens: int
    output_tokens: int
    cost_usd: float | None  # None when the provider does not report a cost
    duration_ms: int


class UsageMeter:
    """Collects the calls of one run; safe to share between worker threads."""

    def __init__(self) -> None:
        self._calls: list[CallUsage] = []
        self._lock = threading.Lock()

    def add(self, call: CallUsage) -> None:
        with self._lock:
            self._calls.append(call)

    @property
    def calls(self) -> list[CallUsage]:
        with self._lock:
            return list(self._calls)

    def summary(self) -> dict[str, Any]:
        """Totals for the run stats, overall and per purpose."""
        calls = self.calls
        by_purpose: dict[str, list[CallUsage]] = {}
        for call in calls:
            by_purpose.setdefault(call.purpose, []).append(call)
        return {
            **_totals(calls),
            "by_purpose": {purpose: _totals(group) for purpose, group in by_purpose.items()},
        }


def _totals(calls: list[CallUsage]) -> dict[str, Any]:
    costs = [call.cost_usd for call in calls if call.cost_usd is not None]
    return {
        "calls": len(calls),
        "input_tokens": sum(call.input_tokens for call in calls),
        "output_tokens": sum(call.output_tokens for call in calls),
        # A partial sum would understate spending; report it only when every call had a cost.
        "cost_usd": round(sum(costs), 6) if calls and len(costs) == len(calls) else None,
        "duration_ms": sum(call.duration_ms for call in calls),
    }
