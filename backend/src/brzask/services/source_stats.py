"""Source survival: do the sources brzask adds itself stay, and get read?

Sources come from the reader (manual), discovery (web search and the judge),
opened links (visited) or an OPML import. For each origin, and for discovery
each search adapter, the sources enabled at least `age` ago are followed up:
are they still active, have their articles reached a digest, has the reader
opened one? Younger sources are counted but not judged yet.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from brzask.db.models import SourceOrigin, SourceStatus
from brzask.repositories import SourceRepository
from brzask.repositories.sources import SourceRecord

AGE = timedelta(days=30)
# Statuses a source can only reach after being enabled; pending and rejected
# sources were never read.
ENABLED_ONCE = {SourceStatus.ACTIVE, SourceStatus.MUTED, SourceStatus.DEAD}
# Discovery records `<adapter>: <interest>`; sources added before it did have none.
UNRECORDED = "not recorded"


@dataclass(frozen=True, slots=True)
class Survival:
    origin: SourceOrigin
    adapter: str | None  # the search adapter, for discovery only
    added: int  # every source of this origin, rejected and pending included
    enabled: int  # read at some point (active, muted or dead now)
    old_enough: int  # enabled, and added at least `age` ago: the ones judged below
    still_active: int
    shown: int  # had an article in a digest
    opened: int  # had an article opened
    opens: int  # articles opened, in total


def adapter_of(record: SourceRecord) -> str | None:
    if record.origin is not SourceOrigin.DISCOVERY:
        return None
    detail = (record.origin_detail or "").partition(":")[0].strip()
    return detail or UNRECORDED


def survival(
    records: Iterable[SourceRecord], now: datetime, age: timedelta = AGE
) -> list[Survival]:
    """One row per origin (and discovery adapter), in origin order, then by adapter."""
    groups: dict[tuple[SourceOrigin, str | None], list[SourceRecord]] = {}
    for record in records:
        groups.setdefault((record.origin, adapter_of(record)), []).append(record)
    rows = []
    for (origin, adapter), group in groups.items():
        enabled = [r for r in group if r.status in ENABLED_ONCE]
        judged = [r for r in enabled if r.created_at <= now - age]
        rows.append(
            Survival(
                origin=origin,
                adapter=adapter,
                added=len(group),
                enabled=len(enabled),
                old_enough=len(judged),
                still_active=sum(r.status is SourceStatus.ACTIVE for r in judged),
                shown=sum(r.shown > 0 for r in judged),
                opened=sum(r.opened > 0 for r in judged),
                opens=sum(r.opened for r in judged),
            )
        )
    order = list(SourceOrigin)
    return sorted(rows, key=lambda row: (order.index(row.origin), row.adapter or ""))


def source_survival(session: Session, now: datetime, age: timedelta = AGE) -> list[Survival]:
    return survival(SourceRepository(session).records(), now, age)
