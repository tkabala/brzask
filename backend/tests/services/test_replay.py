"""Replaying past digests, on Postgres, with a fake model."""

import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from brzask import prompts
from brzask.clients.llm import Completion, LLMError
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.db.models import Article, Run
from brzask.services.digest.dedup import THRESHOLDS
from brzask.services.digest.pool import POOL_CAP
from brzask.services.replay import (
    PoolConfig,
    ReplayClients,
    ReplayConfig,
    replay,
    replay_pool,
    report,
    summarize,
    with_stored_text,
)
from tests.factories import TEST_MODEL, Factories, unit_vector
from tests.services.digest.fakes import NOW

TODAY = NOW.date()
YESTERDAY = TODAY - timedelta(days=1)


class FakeModel:
    """Ranks in pool order and selects every candidate it is shown; keeps the prompts."""

    def __init__(self, fail_selection: bool = False) -> None:
        self.prompts: dict[str, list[str]] = {"ranking": [], "selection": []}
        self.fail_selection = fail_selection

    def complete_json(
        self, prompt: str, *, purpose: str, meter: UsageMeter | None = None
    ) -> tuple[Any, Completion]:
        self.prompts[purpose].append(prompt)
        usage = CallUsage("test/model", purpose, 100, 10, 0.001, 1)
        if meter is not None:
            meter.add(usage)
        if purpose == "ranking":
            return {"ranking": list(range(1, 41))}, Completion("{}", usage)
        if self.fail_selection:
            raise LLMError("the API kept failing")
        links = re.findall(r"^\d+\. \[.*?\]\((\S+)\)$", prompt, re.MULTILINE)
        articles = [{"link": link, "title": f"T {link}", "topic": "X"} for link in links]
        return {"articles": articles}, Completion("{}", usage)


def clients(model: FakeModel) -> ReplayClients:
    return ReplayClients(
        llm=model,
        llm_model="test/model",
        embedding_model=TEST_MODEL,
        language=prompts.language("en"),
    )


@pytest.fixture
def history(make: Factories) -> dict[str, Article]:
    """Two digest days: yesterday's run showed `opened` and `ignored`, today's `fresh`."""
    lobsters, blog = make.source("Lobsters"), make.source("Blog")
    yesterday_run, today_run = NOW - timedelta(days=1), NOW
    return {
        "opened": make.article(
            lobsters,
            title="Opened",
            first_seen_at=yesterday_run - timedelta(hours=1),
            digest_date=YESTERDAY,
            shown_at=yesterday_run,
            opened_at=yesterday_run + timedelta(hours=3),
        ),
        "ignored": make.article(
            blog,
            title="Ignored",
            first_seen_at=yesterday_run - timedelta(hours=1),
            digest_date=YESTERDAY,
            shown_at=yesterday_run,
        ),
        "unshown": make.article(
            blog, title="Unshown", first_seen_at=yesterday_run - timedelta(hours=1)
        ),
        "fresh": make.article(
            lobsters,
            title="Fresh",
            first_seen_at=today_run - timedelta(hours=1),
            digest_date=TODAY,
            shown_at=today_run,
            opened_at=today_run + timedelta(hours=1),
        ),
        "skipped": make.article(
            blog, title="Skipped", first_seen_at=today_run - timedelta(hours=1)
        ),
    }


def test_each_day_is_chosen_again_from_what_it_could_see(
    sessions: sessionmaker[Session], session: Session, history: dict[str, Article]
) -> None:
    model = FakeModel()

    days = replay(sessions, clients(model), since=YESTERDAY)

    assert [day.day for day in days] == [YESTERDAY, TODAY]
    first, second = days
    assert {pick.link for pick in first.picks} == {
        history[name].link for name in ("opened", "ignored", "unshown")
    }
    assert (first.pool, first.opened_in_pool, first.shown, first.shown_opened) == (3, 1, 2, 1)
    assert (first.picked_opened, first.same) == (1, 2)
    # Shown yesterday, so not candidates today.
    assert {pick.link for pick in second.picks} == {
        history[name].link for name in ("unshown", "fresh", "skipped")
    }
    assert (second.picked_opened, second.same, second.shown_opened) == (1, 1, 1)

    # The ranking saw only opens from before each run.
    yesterday_prompt, today_prompt = model.prompts["ranking"]
    assert "- Opened" not in yesterday_prompt
    assert "- Opened" in today_prompt

    summary = summarize(days)
    assert (summary.days, summary.picked, summary.picked_opened) == (2, 6, 2)
    assert (summary.shown, summary.shown_opened, summary.same) == (3, 2, 3)
    assert summary.usage["calls"] == 4


def test_a_replay_writes_nothing(
    sessions: sessionmaker[Session], session: Session, history: dict[str, Article]
) -> None:
    replay(sessions, clients(FakeModel()), since=YESTERDAY)

    assert session.scalar(select(func.count()).select_from(Run)) == 0
    assert session.scalars(select(Article.rank).where(Article.rank.is_not(None))).all() == []
    assert history["unshown"].digest_date is None


def test_a_failed_day_is_reported_and_left_out_of_the_totals(
    sessions: sessionmaker[Session], history: dict[str, Article]
) -> None:
    days = replay(sessions, clients(FakeModel(fail_selection=True)), since=TODAY)

    (day,) = days
    assert day.error == "LLMError: the API kept failing"
    assert day.picks == []
    summary = summarize(days)
    assert (summary.days, summary.failed, summary.shown) == (0, 1, 0)
    assert summary.usage["calls"] == 2  # the failed call is still paid for


def test_the_report_has_every_day_and_pick(
    sessions: sessionmaker[Session], history: dict[str, Article]
) -> None:
    model = FakeModel()
    config = ReplayConfig(llm_model="other/model")
    days = replay(sessions, clients(model), since=TODAY, config=config)

    data = report(days, clients(model), config)

    assert data["config"]["llm_model"] == "other/model"
    assert data["summary"]["picked_opened"] == 1
    (day,) = data["days"]
    assert day["day"] == TODAY.isoformat()
    assert {pick["title"] for pick in day["picks"]} == {
        f"T {history[name].link}" for name in ("unshown", "fresh", "skipped")
    }
    assert day["stats"]["ranking"]["top"] == 3


def test_the_pool_drops_stale_articles_and_keeps_the_cap(session: Session, make: Factories) -> None:
    source = make.source()
    stale = make.article(source, published_at=NOW - timedelta(days=11))
    articles = [stale, *(make.article(source, published_at=NOW) for _ in range(3))]

    pool = replay_pool(articles, NOW, PoolConfig())
    capped = replay_pool(articles, NOW, PoolConfig(cap=2))

    assert stale.link not in {c.link for c in pool}
    assert len(pool) == 3
    assert len(capped) == 2
    assert PoolConfig().cap == POOL_CAP


def test_stored_text_and_vectors_of_the_same_model_are_used(
    session: Session, make: Factories
) -> None:
    source = make.source()
    same = make.article(source, extracted_text="Text", embedding=unit_vector(0, 1))
    other = make.article(
        source, extracted_text="Other", embedding=unit_vector(1, 1), embedding_model="other"
    )
    candidates = replay_pool([same, other], NOW, PoolConfig())

    stored = with_stored_text(candidates, {same.id: same, other.id: other}, TEST_MODEL)
    by_link = {c.link: c for c in stored}

    assert by_link[same.link].text == "Text"
    assert by_link[same.link].embedding == pytest.approx(unit_vector(0, 1))
    assert by_link[other.link].text == "Other"
    assert by_link[other.link].embedding is None


def test_config_from_toml(tmp_path: Path) -> None:
    path = tmp_path / "candidate.toml"
    path.write_text(
        'llm_model = "x/y"\n'
        "[ranking]\ntop_n = 20\n"
        "[deduplication]\ncross_day = 0.95\nsame_day = [0.85, 0.9]\n"
    )

    config = ReplayConfig.load(path)

    assert config.llm_model == "x/y"
    assert config.limits().top_n == 20
    assert config.limits().max_per_source == 2  # left out: the digest's own value
    assert config.thresholds(TEST_MODEL).same_day == (0.85, 0.9)
    assert (
        ReplayConfig().thresholds("google/gemini-embedding-001")
        == (THRESHOLDS["gemini-embedding-001"])
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[ranking]\ntop_m = 20\n", "top_m"),  # misspelt: never ignored
        ("[ranking]\ntop_n = 0\n", "greater than 0"),
        ("[deduplication]\ncross_day = 0.95\n", "same_day"),
        ("[ranking\n", "Expected"),
    ],
)
def test_config_errors_name_the_problem(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "candidate.toml"
    path.write_text(text)

    with pytest.raises(ValueError, match=message):
        ReplayConfig.load(path)
