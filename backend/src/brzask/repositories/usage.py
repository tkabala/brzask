"""SQL over the usage summaries stored on runs and answers (`UsageMeter.summary`)."""

from typing import Any

from sqlalchemy import ColumnElement, Numeric, and_, case, cast, func, or_


def usage_cost(usage: Any) -> tuple[ColumnElement[Any], ColumnElement[bool]]:
    """The reported cost of a stored usage summary, and whether it has unpriced calls.

    Summaries recorded before usage had `cost_usd_known` count their
    `cost_usd`, unpriced when it is null.
    """

    def number(key: str) -> ColumnElement[Any]:
        # Only JSON numbers are cast: one odd value must not fail every check.
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
    return cost, unpriced
