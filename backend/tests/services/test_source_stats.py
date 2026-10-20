from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from brzask.db.models import SourceOrigin, SourceStatus
from brzask.repositories.sources import SourceRecord
from brzask.services.source_stats import UNRECORDED, source_survival, survival
from tests.factories import Factories

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)
OLD = NOW - timedelta(days=45)
YOUNG = NOW - timedelta(days=5)


def record(
    origin: SourceOrigin,
    status: SourceStatus = SourceStatus.ACTIVE,
    created_at: datetime = OLD,
    detail: str | None = None,
    shown: int = 0,
    opened: int = 0,
) -> SourceRecord:
    return SourceRecord(0, origin, detail, status, created_at, shown + 5, shown, opened)


def test_survival_by_origin_and_discovery_adapter() -> None:
    records = [
        record(SourceOrigin.DISCOVERY, detail="llm-online: Rust", shown=3, opened=2),
        record(SourceOrigin.DISCOVERY, SourceStatus.MUTED, detail="llm-online: Rust"),
        record(SourceOrigin.DISCOVERY, SourceStatus.REJECTED, detail="llm-online: Go"),
        record(SourceOrigin.DISCOVERY, created_at=YOUNG, detail="llm-online: Go", opened=1),
        record(SourceOrigin.DISCOVERY, SourceStatus.DEAD, detail="searxng: Rust", shown=1),
        record(SourceOrigin.DISCOVERY, shown=1),
        record(SourceOrigin.MANUAL, opened=4, shown=4),
        record(SourceOrigin.VISITED, SourceStatus.PENDING, created_at=YOUNG),
    ]

    rows = {(row.origin, row.adapter): row for row in survival(records, NOW)}

    assert list(rows) == [
        (SourceOrigin.MANUAL, None),
        (SourceOrigin.DISCOVERY, "llm-online"),
        (SourceOrigin.DISCOVERY, UNRECORDED),
        (SourceOrigin.DISCOVERY, "searxng"),
        (SourceOrigin.VISITED, None),
    ]
    online = rows[(SourceOrigin.DISCOVERY, "llm-online")]
    assert (online.added, online.enabled, online.old_enough) == (4, 3, 2)
    assert (online.still_active, online.shown, online.opened, online.opens) == (1, 1, 1, 2)
    searxng = rows[(SourceOrigin.DISCOVERY, "searxng")]
    assert (searxng.still_active, searxng.shown) == (0, 1)
    visited = rows[(SourceOrigin.VISITED, None)]
    assert (visited.added, visited.enabled, visited.old_enough) == (1, 0, 0)


def test_the_age_is_a_parameter() -> None:
    records = [record(SourceOrigin.MANUAL, created_at=YOUNG)]

    (default,) = survival(records, NOW)
    (short,) = survival(records, NOW, timedelta(days=3))

    assert (default.old_enough, short.old_enough) == (0, 1)


def test_records_count_each_sources_articles(session: Session, make: Factories) -> None:
    source = make.source(origin=SourceOrigin.DISCOVERY, origin_detail="brave: Rust")
    make.source()  # no articles
    make.article(source, digest_date=NOW.date(), opened_at=NOW)
    make.article(source)

    rows = source_survival(session, datetime.now(UTC) + timedelta(days=31))

    discovery = next(row for row in rows if row.origin is SourceOrigin.DISCOVERY)
    assert (discovery.adapter, discovery.old_enough, discovery.opened, discovery.opens) == (
        "brave",
        1,
        1,
        1,
    )
    manual = next(row for row in rows if row.origin is SourceOrigin.MANUAL)
    assert (manual.old_enough, manual.shown) == (1, 0)
