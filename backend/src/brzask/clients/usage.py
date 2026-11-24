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
        # What spending limits sum: the reported part, with the unpriced calls counted.
        "cost_usd_known": round(float(sum(costs)), 6),
        "unpriced_calls": len(calls) - len(costs),
        "duration_ms": sum(call.duration_ms for call in calls),
    }


_SUMMED = ("calls", "input_tokens", "output_tokens", "unpriced_calls", "duration_ms")


def combined(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Two summaries as one, as if their calls had gone through one meter.

    For a record that gathers calls over several requests, such as an answer
    asked again or searched for later. An empty dict is a summary of no calls.
    """
    if not first:
        return dict(second)
    if not second:
        return dict(first)
    purposes = {**first.get("by_purpose", {}), **second.get("by_purpose", {})}
    return {
        **_add(first, second),
        "by_purpose": {
            purpose: _add(
                first.get("by_purpose", {}).get(purpose, {}),
                second.get("by_purpose", {}).get(purpose, {}),
            )
            for purpose in purposes
        },
    }


def _add(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    totals: dict[str, Any] = {key: first.get(key, 0) + second.get(key, 0) for key in _SUMMED}
    known = round(float(first.get("cost_usd_known", 0) + second.get("cost_usd_known", 0)), 6)
    priced = totals["calls"] and not totals["unpriced_calls"]
    return {
        "calls": totals["calls"],
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"],
        "cost_usd": known if priced else None,
        "cost_usd_known": known,
        "unpriced_calls": totals["unpriced_calls"],
        "duration_ms": totals["duration_ms"],
    }
