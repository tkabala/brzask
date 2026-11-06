"""The first archive format stays importable.

`archive-v1.jsonl.gz` was written once by `brzask export` (format version 1)
and is never regenerated. When a schema change makes this test fail, people
holding archives of that version would fail the same way: teach the import to
read the old rows (fill or rename the column in `decode_row` or before the
insert) instead of writing a new file.

To write the file once: BRZASK_WRITE_GOLDEN=1 uv run pytest tests/services/test_archive_golden.py
"""

import io
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from brzask.db.models import (
    ApiToken,
    Article,
    ArticleEmbedding,
    ArticleState,
    Change,
    ChangeStatus,
    Setting,
    SourceStatus,
    TokenScope,
)
from brzask.services.archive import export_archive, import_archive
from tests.factories import Factories

GOLDEN = Path(__file__).parent.parent / "fixtures" / "archive" / "archive-v1.jsonl.gz"
AT = datetime(2026, 11, 6, 5, 0, tzinfo=UTC)


def build_golden(session: Session, make: Factories) -> None:
    feed = make.source(name="Feed", site_url="https://feed.example/", fetched_at=AT, etag='"e1"')
    make.source(
        name="Muted",
        status=SourceStatus.MUTED,
        note="never opened",
        fetch_failures=2,
        failing_since=AT - timedelta(days=1),
        failed_at=AT,
        fetch_error="HTTP 503",
    )
    make.interest(topic="AI", keywords=["llm", "agents"], notes="want: evals; skip: funding")
    make.article(feed, first_seen_at=AT, snippet="Seen only.")
    make.article(
        feed,
        first_seen_at=AT,
        digest_date=date(2026, 11, 6),
        rank=1,
        opened_at=AT + timedelta(hours=3),
        extracted_text="Full text.",
        extracted_by="trafilatura",
        digest_title="Tytuł",
        summary="A summary.",
        why_it_matters="Because.",
        topic="AI",
        embedding=[0.125] * 768,
    )
    make.article(feed, first_seen_at=AT, state=ArticleState.REPEAT, embedding=[-0.5] * 768)
    make.run(AT, cost=0.0042)
    session.add_all(
        [
            Setting(key="embedding_model", value={"model": "test/model"}),
            Change(
                actor="pipeline:review",
                action="source.mute",
                entity_type="source",
                entity_id="2",
                before={"status": "active"},
                after={"status": "muted"},
                reason="never opened",
                status=ChangeStatus.APPLIED,
                decided_at=AT,
            ),
            ApiToken(name="reader", prefix="brz_gold", token_hash="a" * 64, scope=TokenScope.FEED),
        ]
    )
    session.flush()


@pytest.mark.skipif(not os.environ.get("BRZASK_WRITE_GOLDEN"), reason="writes the golden file")
def test_write_the_golden_archive(session: Session, make: Factories) -> None:
    build_golden(session, make)
    out = io.BytesIO()
    export_archive(session, out, version="0.1.17")
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_bytes(out.getvalue())


def test_the_v1_archive_still_imports(session: Session, sessions: sessionmaker[Session]) -> None:
    with GOLDEN.open("rb") as archive:
        counts = import_archive(sessions, archive)

    assert counts == {
        "sources": 2,
        "interests": 1,
        "articles": 3,
        "article_embeddings": 2,
        "runs": 1,
        "settings": 1,
        "change_log": 1,
        "api_tokens": 1,
    }
    shown = session.scalars(select(Article).where(Article.digest_date.is_not(None))).one()
    assert (shown.digest_position, shown.digest_title, shown.state) == (1, "Tytuł", "shown")
    assert shown.opened_at == AT + timedelta(hours=3)
    vector = session.scalars(
        select(ArticleEmbedding.embedding).where(ArticleEmbedding.article_id == shown.id)
    ).one()
    assert list(vector) == [0.125] * 768
