"""Factories for test rows: sensible defaults, override what the test is about."""

import itertools
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from brzask.db.models import (
    EMBEDDING_DIMENSIONS,
    Article,
    ArticleState,
    Interest,
    Source,
    SourceKind,
    SourceOrigin,
    SourceStatus,
)
from brzask.repositories import ArticleRepository

TEST_MODEL = "test/embedding"


def unit_vector(*weights: float) -> list[float]:
    """A normalised vector whose first components are `weights`, the rest zero.

    `unit_vector(1, 0)` and `unit_vector(1, 1)` have cosine similarity 0.707.
    """
    norm = math.sqrt(sum(weight * weight for weight in weights))
    padded = [weight / norm for weight in weights]
    return padded + [0.0] * (EMBEDDING_DIMENSIONS - len(padded))


class Factories:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._sequence = itertools.count(1)

    def _add[T](self, row: T) -> T:
        self.session.add(row)
        self.session.flush()
        return row

    def source(
        self,
        name: str | None = None,
        *,
        status: SourceStatus = SourceStatus.ACTIVE,
        kind: SourceKind = SourceKind.FEED,
        origin: SourceOrigin = SourceOrigin.MANUAL,
        **fields: Any,
    ) -> Source:
        n = next(self._sequence)
        fields.setdefault("url", f"https://source-{n}.example/feed.xml")
        return self._add(
            Source(name=name or f"Source {n}", status=status, kind=kind, origin=origin, **fields)
        )

    def interest(
        self,
        topic: str | None = None,
        *,
        keywords: Sequence[str] = (),
        notes: str = "",
        active: bool = True,
    ) -> Interest:
        n = next(self._sequence)
        return self._add(
            Interest(
                topic=topic or f"Topic {n}", keywords=list(keywords), notes=notes, active=active
            )
        )

    def article(
        self,
        source: Source | None = None,
        *,
        first_seen_at: datetime | None = None,
        embedding: Sequence[float] | None = None,
        embedding_model: str | None = None,
        digest_date: date | None = None,
        digest_position: int | None = None,
        **fields: Any,
    ) -> Article:
        """An article; giving `digest_date` makes it shown in that day's digest.

        The position defaults to the next free one for that day, `shown_at`
        to `first_seen_at`.
        """
        n = next(self._sequence)
        fields.setdefault("link", f"https://news.example/articles/{n}")
        fields.setdefault("title", f"Article {n}")
        seen = first_seen_at or datetime.now(UTC)
        if embedding is not None:
            fields["embedding"] = list(embedding)
            fields["embedding_model"] = embedding_model or TEST_MODEL
        if digest_date is not None:
            fields.setdefault("state", ArticleState.SHOWN)
            fields.setdefault("shown_at", seen)
            fields["digest_date"] = digest_date
            fields["digest_position"] = (
                digest_position
                if digest_position is not None
                else (ArticleRepository(self.session).last_digest_position(digest_date) or 0) + 1
            )
        return self._add(
            Article(source_id=source.id if source else None, first_seen_at=seen, **fields)
        )
