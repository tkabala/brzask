"""Feeds and their per-source statistics."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brzask.db.models import Article, ArticleState, Source, SourceKind, SourceOrigin, SourceStatus


@dataclass(frozen=True, slots=True)
class SourceStats:
    """What one source produced in a time window."""

    source_id: int
    articles: int
    ranked: int  # made the top of the ranking (rank set)
    shown: int
    opened: int


class SourceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, source_id: int) -> Source | None:
        return self.session.get(Source, source_id)

    def get_by_url(self, url: str) -> Source | None:
        return self.session.scalars(select(Source).where(Source.url == url)).one_or_none()

    def find(self, *statuses: SourceStatus) -> Sequence[Source]:
        """All sources by name, or only those with one of `statuses`."""
        query = select(Source).order_by(Source.name)
        if statuses:
            query = query.where(Source.status.in_(statuses))
        return self.session.scalars(query).all()

    def get_by_name(self, name: str) -> Source | None:
        """Names are compared ignoring case, as people type them (and unique that way)."""
        query = select(Source).where(func.lower(Source.name) == func.lower(name))
        return self.session.scalars(query).one_or_none()

    def count_by_status(self) -> dict[SourceStatus, int]:
        query = select(Source.status, func.count()).group_by(Source.status)
        return {status: count for status, count in self.session.execute(query)}

    def add(
        self,
        *,
        name: str,
        url: str,
        status: SourceStatus,
        origin: SourceOrigin,
        kind: SourceKind = SourceKind.FEED,
        site_url: str | None = None,
        origin_detail: str | None = None,
        note: str | None = None,
    ) -> Source | None:
        """Insert a source; None when its feed URL or name is already taken.

        A known URL counts whatever its status: rejected sources keep their row,
        so a URL is never proposed twice.
        """
        statement = (
            insert(Source)
            .values(
                name=name,
                url=url,
                status=status,
                origin=origin,
                kind=kind,
                site_url=site_url,
                origin_detail=origin_detail,
                note=note,
            )
            .on_conflict_do_nothing()
            .returning(Source)
        )
        return self.session.scalars(statement).one_or_none()

    def set_status(self, source: Source, status: SourceStatus, note: str | None = None) -> None:
        source.status = status
        source.note = note
        self.session.flush()

    def set_fetch_validators(
        self, source: Source, etag: str | None, last_modified: str | None
    ) -> None:
        """Remember the feed's validators, sent back on the next fetch."""
        source.etag = etag
        source.last_modified = last_modified
        self.session.flush()

    def stats(self, since: datetime) -> dict[int, SourceStats]:
        """Counts per source for articles first seen at or after `since`.

        Grouped by `source_id`, so renaming a source keeps its history. Every
        source is present, with zeros when it published nothing.
        """
        window = (
            select(
                Article.source_id,
                func.count().label("articles"),
                func.count(Article.rank).label("ranked"),
                func.count().filter(Article.state == ArticleState.SHOWN).label("shown"),
                func.count(Article.opened_at).label("opened"),
            )
            .where(Article.first_seen_at >= since)
            .group_by(Article.source_id)
            .subquery()
        )
        query = select(
            Source.id,
            func.coalesce(window.c.articles, 0),
            func.coalesce(window.c.ranked, 0),
            func.coalesce(window.c.shown, 0),
            func.coalesce(window.c.opened, 0),
        ).outerjoin(window, window.c.source_id == Source.id)
        return {
            source_id: SourceStats(source_id, articles, ranked, shown, opened)
            for source_id, articles, ranked, shown, opened in self.session.execute(query)
        }
