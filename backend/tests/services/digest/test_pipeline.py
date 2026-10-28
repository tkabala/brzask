"""The digest pipeline end to end, on Postgres, with fake clients."""

import re
from dataclasses import replace
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from brzask import prompts
from brzask.clients.feeds import FeedEntry, FeedResult, FetchStatus
from brzask.clients.llm import Completion
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.db.models import Article, ArticleState, RunKind, RunStatus, Source
from brzask.repositories import ArticleRepository, EmbeddingRepository
from brzask.services.digest import pipeline
from brzask.services.digest.pipeline import DigestClients, build_digest, run_digest
from brzask.services.digest.selection import DIGEST_SIZE
from brzask.services.embeddings import switch_model
from brzask.services.pause import pause
from brzask.services.runs import RunContext, run_pipeline
from tests.factories import TEST_MODEL, Factories, unit_vector
from tests.services.digest.fakes import (
    NOW,
    FakeEmbedder,
    FakeExtractor,
    FakeFeeds,
    FakeJudge,
    context,
)

WARSAW = ZoneInfo("Europe/Warsaw")
# 07:00 UTC on 18 October is 09:00 in Warsaw: the digest date is the 18th.
TODAY = NOW.astimezone(WARSAW).date()


class FakeModel:
    """Ranks candidates in pool order and picks the first links of the selection prompt."""

    def __init__(self, selection: Any = None) -> None:
        self.selection = selection
        self.purposes: list[str] = []

    def complete_json(
        self, prompt: str, *, purpose: str, meter: UsageMeter | None = None
    ) -> tuple[Any, Completion]:
        self.purposes.append(purpose)
        usage = CallUsage("test/model", purpose, 100, 10, 0.001, 1)
        if meter is not None:
            meter.add(usage)
        if purpose == "ranking":
            return {"ranking": list(range(1, 41))}, Completion("{}", usage)
        if self.selection is not None:
            return self.selection, Completion("{}", usage)
        links = re.findall(r"^\d+\. \[.*?\]\((\S+)\)$", prompt, re.MULTILINE)
        articles = [
            {"link": link, "title": f"T {link}", "summary": "S", "whyItMatters": "W", "topic": "X"}
            for link in links[:DIGEST_SIZE]
        ]
        return {"articles": articles}, Completion("{}", usage)


def feeds_for(sources: list[Source], per_source: int = 4) -> FakeFeeds:
    """Entries with distinct text, so deduplication keeps them all."""
    return FakeFeeds(
        {
            source.url: FeedResult(
                source.url,
                FetchStatus.OK,
                [
                    FeedEntry(link, link, f"About {link}", None, NOW - timedelta(hours=n))
                    for n in range(per_source)
                    for link in [f"https://{source.id}.example/{n}"]
                ],
            )
            for source in sources
        }
    )


def clients(feeds: FakeFeeds, model: FakeModel | None = None) -> DigestClients:
    return DigestClients(
        feeds=feeds,
        llm=model or FakeModel(),
        extractor=FakeExtractor(),
        embedder=FakeEmbedder(),
        language=prompts.language("en"),
        timezone=WARSAW,
    )


def run(
    sessions: sessionmaker[Session],
    digest: DigestClients,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> Any:
    def pipeline(context: RunContext) -> None:
        context.started_at = NOW
        build_digest(context, digest)

    return run_pipeline(
        sessions,
        RunKind.DIGEST,
        dry_run=dry_run,
        force=force,
        pipelines={RunKind.DIGEST: pipeline},
    )


def shown(session: Session) -> list[Article]:
    session.expire_all()
    return list(ArticleRepository(session).digest(TODAY))


def test_a_run_builds_and_stores_todays_digest(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    sources = [make.source() for _ in range(6)]
    model = FakeModel()

    finished = run(sessions, clients(feeds_for(sources), model))

    assert finished.status is RunStatus.OK, finished.error
    digest = shown(session)
    assert [a.digest_position for a in digest] == list(range(1, DIGEST_SIZE + 1))
    assert all(a.state is ArticleState.SHOWN and a.shown_at == NOW for a in digest)
    assert digest[0].digest_title == f"T {digest[0].link}"
    assert (digest[0].summary, digest[0].why_it_matters, digest[0].topic) == ("S", "W", "X")
    assert all(a.rank is not None for a in digest)
    vectors = EmbeddingRepository(session).of_articles([a.id for a in digest], TEST_MODEL)
    assert vectors.keys() == {a.id for a in digest}
    assert model.purposes == ["ranking", "selection"]
    stats = finished.stats
    assert stats["date"] == TODAY.isoformat()
    assert {"pool", "ranking", "extraction", "deduplication", "selection", "usage"} <= set(stats)
    assert stats["usage"]["calls"] == 2
    # The rest of the pool stays seen, to be carried over.
    stored = session.scalar(select(func.count()).select_from(Article)) or 0
    assert stored == 6 * 4


def test_todays_digest_is_built_once_unless_forced(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    sources = [make.source() for _ in range(6)]
    run(sessions, clients(feeds_for(sources)))

    again = run(sessions, clients(feeds_for(sources)))
    assert again.status is RunStatus.SKIPPED
    assert again.stats["reason"] == "today's digest already exists"

    forced = run(sessions, clients(feeds_for(sources, per_source=6)), force=True)
    assert forced.status is RunStatus.OK, forced.error
    positions = [a.digest_position for a in shown(session)]
    assert positions == list(range(1, 2 * DIGEST_SIZE + 1))


def test_a_paused_digest_is_skipped_unless_forced(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    sources = [make.source() for _ in range(6)]
    pause(session, NOW + timedelta(days=3), NOW, actor="user")

    skipped = run(sessions, clients(feeds_for(sources)))
    assert skipped.status is RunStatus.SKIPPED
    assert skipped.stats["reason"].startswith("paused until ")

    forced = run(sessions, clients(feeds_for(sources)), force=True)
    assert forced.status is RunStatus.OK
    assert len(shown(session)) == DIGEST_SIZE


def test_a_repeat_of_a_shown_article_is_marked_to_stay_out(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    sources = [make.source() for _ in range(6)]
    yesterday = NOW - timedelta(days=1)
    make.article(first_seen_at=yesterday, digest_date=yesterday.date(), embedding=unit_vector(1))
    repeat = f"https://{sources[0].id}.example/0"
    embedder = FakeEmbedder()
    embedder.vectors[f"About {repeat}"] = unit_vector(1)  # the shown article's vector
    digest = replace(clients(feeds_for(sources)), embedder=embedder)

    finished = run(sessions, digest)

    assert finished.status is RunStatus.OK, finished.error
    assert finished.stats["deduplication"]["cross_day_dropped"] == 1
    stored = session.scalars(select(Article).where(Article.link == repeat)).one()
    assert stored.state is ArticleState.REPEAT
    others = session.scalars(select(Article).where(Article.state == ArticleState.REPEAT)).all()
    assert others == [stored]


def test_a_dry_run_writes_nothing_but_the_run(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    sources = [make.source() for _ in range(6)]

    finished = run(sessions, clients(feeds_for(sources)), dry_run=True)

    assert finished.status is RunStatus.OK, finished.error
    assert finished.stats["selection"]["picked"] == DIGEST_SIZE
    assert shown(session) == []
    assert session.scalar(select(func.count()).select_from(Article)) == 0
    assert all(source.fetched_at is None for source in sources)


def test_no_candidates_skips_the_run(sessions: sessionmaker[Session]) -> None:
    finished = run(sessions, clients(FakeFeeds({})))

    assert finished.status is RunStatus.SKIPPED
    assert finished.stats["reason"] == "no candidates"


def test_a_failed_selection_shows_nothing_and_keeps_the_pool(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    sources = [make.source() for _ in range(3)]
    model = FakeModel(selection={"articles": [{"link": "https://invented.example/"}]})

    with pytest.raises(Exception, match="named none of the candidates"):
        run(sessions, clients(feeds_for(sources), model))

    assert shown(session) == []
    stored = session.scalars(select(Article)).all()
    assert len(stored) == 12
    assert all(article.state is ArticleState.SEEN for article in stored)


def test_the_digest_embeds_with_the_active_model(
    sessions: sessionmaker[Session], session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    switch_model(session, "new/embedding", TEST_MODEL, actor="user")
    monkeypatch.setenv("EMBEDDING_MODEL", TEST_MODEL)
    built: list[str] = []

    def build(context: RunContext, clients: DigestClients) -> None:
        built.append(clients.embedder.model)

    monkeypatch.setattr(pipeline, "build_digest", build)
    run_digest(context(sessions))

    assert built == ["new/embedding"]


@pytest.mark.parametrize(("ranking", "judge_model"), [("llm", None), ("judge", "liquid/d1")])
def test_the_ranking_setting_decides_whether_a_judge_ranks(
    sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    ranking: str,
    judge_model: str | None,
) -> None:
    monkeypatch.setenv("DIGEST_RANKING", ranking)
    monkeypatch.setenv("JUDGE_MODEL", "liquid/d1")
    built: list[str | None] = []

    def build(context: RunContext, clients: DigestClients) -> None:
        built.append(clients.judge.model if clients.judge else None)

    monkeypatch.setattr(pipeline, "build_digest", build)
    run_digest(context(sessions))

    assert built == [judge_model]


def test_a_judge_ranks_the_pool_when_given(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    sources = [make.source() for _ in range(6)]
    model = FakeModel()
    digest = replace(clients(feeds_for(sources), model), judge=FakeJudge())

    finished = run(sessions, digest)

    assert finished.status is RunStatus.OK, finished.error
    assert model.purposes == ["selection"]
    assert finished.stats["ranking"]["method"] == "judge"
    assert finished.stats["usage"]["by_purpose"]["ranking"]["calls"] == 6 * 4


@pytest.mark.parametrize(
    ("ranking", "deduplication", "expected"),
    [("llm", "judge", (False, True)), ("judge", "judge", (True, True))],
)
def test_one_judge_serves_ranking_and_deduplication_as_set(
    sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    ranking: str,
    deduplication: str,
    expected: tuple[bool, bool],
) -> None:
    monkeypatch.setenv("DIGEST_RANKING", ranking)
    monkeypatch.setenv("DIGEST_DEDUPLICATION", deduplication)
    built: list[tuple[bool, bool]] = []

    def build(context: RunContext, clients: DigestClients) -> None:
        built.append((clients.judge is not None, clients.dedup_judge is not None))
        if clients.judge and clients.dedup_judge:
            assert clients.judge is clients.dedup_judge

    monkeypatch.setattr(pipeline, "build_digest", build)
    run_digest(context(sessions))

    assert built == [expected]
