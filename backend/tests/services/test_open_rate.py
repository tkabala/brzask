from datetime import UTC, date, datetime, timedelta

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from brzask.services.open_rate import OPEN_RATE_DAYS, recent_opens, register_open_rate
from tests.factories import Factories

LAST = date(2026, 11, 5)
NOW = datetime(2026, 11, 5, 9, tzinfo=UTC)


def digests(make: Factories, days: list[date], opened: dict[date, int]) -> None:
    for day in days:
        for position in range(7):
            make.article(
                digest_date=day,
                opened_at=NOW if position < opened.get(day, 0) else None,
            )
    make.session.flush()


def gauges(reader: InMemoryMetricReader) -> dict[str, tuple[float, dict[str, object]]]:
    data = reader.get_metrics_data()
    if data is None:  # nothing was observed
        return {}
    return {
        metric.name: (point.value, dict(point.attributes or {}))  # type: ignore[union-attr]
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        for point in metric.data.data_points
    }


def test_the_last_seven_digest_days_count(make: Factories, session: Session) -> None:
    # Nine digest days with gaps: the two oldest fall outside the window.
    days = [LAST - timedelta(days=offset) for offset in (0, 1, 2, 4, 5, 6, 8, 9, 10)]
    digests(make, days, opened={days[-1]: 7, days[-2]: 5, days[0]: 3})

    assert OPEN_RATE_DAYS == 7
    assert recent_opens(session) == (49, 3)


def test_no_digest_yet(session: Session) -> None:
    assert recent_opens(session) == (0, 0)


def test_gauges_report_shown_and_opened(make: Factories, sessions: sessionmaker[Session]) -> None:
    digests(make, [LAST, LAST - timedelta(days=1)], opened={LAST: 2})
    reader = InMemoryMetricReader()
    register_open_rate(sessions, MeterProvider(metric_readers=[reader]).get_meter("test"))

    assert gauges(reader) == {
        "brzask.digest.shown": (14, {"days": "7"}),
        "brzask.digest.opened": (2, {"days": "7"}),
    }


def test_gauge_without_database_observes_nothing() -> None:
    engine = create_engine(
        "postgresql+psycopg://brzask:x@127.0.0.1:1/brzask", connect_args={"connect_timeout": 1}
    )
    reader = InMemoryMetricReader()
    register_open_rate(sessionmaker(engine), MeterProvider(metric_readers=[reader]).get_meter("t"))

    assert gauges(reader) == {}
