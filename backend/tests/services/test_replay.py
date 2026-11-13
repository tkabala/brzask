"""Replaying past digests, on Postgres, with a fake model."""

import re
from dataclasses import replace
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
from brzask.repositories import EmbeddingRepository
from brzask.services.digest.pool import POOL_CAP
from brzask.services.digest.scoring import WEIGHTS
from brzask.services.errors import ServiceError
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
from tests.services.digest.fakes import NOW, FakeJudge

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


def clients(model: FakeModel, judge: FakeJudge | None = None) -> ReplayClients:
    return ReplayClients(
        llm=model,
        llm_model="test/model",
        embedding_model=TEST_MODEL,
        language=prompts.language("en"),
        judge=judge,
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
        "fresh": make.article(  # stored by today's run, after it started
            lobsters,
            title="Fresh",
            first_seen_at=today_run + timedelta(minutes=1),
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


def test_a_forced_run_later_that_day_is_left_out_of_the_comparison(
    sessions: sessionmaker[Session], make: Factories, history: dict[str, Article]
) -> None:
    make.article(  # appended by a forced run after the day's run
        title="Forced",
        first_seen_at=NOW + timedelta(hours=2),
        digest_date=TODAY,
        shown_at=NOW + timedelta(hours=3),
        opened_at=NOW + timedelta(hours=4),
    )

    (day,) = replay(sessions, clients(FakeModel()), since=TODAY)

    assert (day.shown, day.shown_opened) == (1, 1)  # only `fresh`, from the first run


def test_a_model_without_stored_vectors_is_refused(
    sessions: sessionmaker[Session], make: Factories, history: dict[str, Article]
) -> None:
    make.article(extracted_text="Text", embedding=unit_vector(0, 1))
    model = FakeModel()
    other = replace(clients(model), embedding_model="typo/model")

    with pytest.raises(ServiceError, match="no vectors of typo/model"):
        replay(sessions, other, since=TODAY)
    assert model.prompts["ranking"] == []


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
    assert day["lost"] == []


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


def test_excluded_sources_leave_the_pool(session: Session, make: Factories) -> None:
    kept, left_out = make.source("Kept"), make.source("Left out")
    articles = [make.article(kept, published_at=NOW), make.article(left_out, published_at=NOW)]

    pool = replay_pool(articles, NOW, PoolConfig(exclude_sources=(left_out.id,)))

    assert [c.link for c in pool] == [articles[0].link]


def test_a_day_names_the_opened_articles_an_exclusion_loses(
    sessions: sessionmaker[Session], history: dict[str, Article]
) -> None:
    lobsters = history["opened"].source_id
    assert lobsters is not None
    config = ReplayConfig(pool=PoolConfig(exclude_sources=(lobsters,)))

    first, second = replay(sessions, clients(FakeModel()), since=YESTERDAY, config=config)
    plain = replay(sessions, clients(FakeModel()), since=YESTERDAY)

    assert first.lost == ["Opened"]
    assert second.lost == ["Fresh"]
    # Only what the pool could still hold counts as openable.
    assert first.opened_in_pool == 0
    assert [day.lost for day in plain] == [[], []]


def test_stored_text_and_vectors_of_the_same_model_are_used(
    session: Session, make: Factories
) -> None:
    source = make.source()
    same = make.article(source, extracted_text="Text", embedding=unit_vector(0, 1))
    other = make.article(
        source, extracted_text="Other", embedding=unit_vector(1, 1), embedding_model="other"
    )
    candidates = replay_pool([same, other], NOW, PoolConfig())

    vectors = EmbeddingRepository(session).of_articles([same.id, other.id], TEST_MODEL)
    stored = with_stored_text(candidates, {same.id: same, other.id: other}, vectors)
    by_link = {c.link: c for c in stored}

    assert by_link[same.link].text == "Text"
    assert by_link[same.link].embedding == pytest.approx(unit_vector(0, 1))
    assert by_link[other.link].text == "Other"
    assert by_link[other.link].embedding is None


def test_config_from_toml(tmp_path: Path) -> None:
    path = tmp_path / "candidate.toml"
    path.write_text(
        'llm_model = "x/y"\n'
        "[pool]\nexclude_sources = [3, 7]\n"
        "[ranking]\ntop_n = 20\n"
        "[deduplication]\ncross_day = 0.95\nsame_day = [0.85, 0.9]\n"
    )

    config = ReplayConfig.load(path)

    assert config.llm_model == "x/y"
    assert config.pool.exclude_sources == (3, 7)
    assert config.limits().top_n == 20
    assert config.limits().max_per_source == 2  # left out: the digest's own value
    thresholds = config.thresholds()
    assert thresholds is not None and thresholds.same_day == (0.85, 0.9)
    assert ReplayConfig().thresholds() is None  # left out: the embedding model's own


def test_a_judge_config_ranks_with_the_judge_and_its_weights(
    sessions: sessionmaker[Session], history: dict[str, Article]
) -> None:
    model = FakeModel()
    judge = FakeJudge({"Skipped": {"depth": 2}, "Unshown": {"interest_fit": 4}})
    config = ReplayConfig.model_validate(
        {"ranking": {"method": "judge", "weights": {"depth": 2.0}}}
    )

    days = replay(sessions, clients(model, judge), since=TODAY, config=config)

    assert model.prompts["ranking"] == []
    assert days[0].stats["ranking"]["method"] == "judge"
    assert len(judge.states) == days[0].pool
    # depth 2 x 2.0 beats interest fit 4 x 1.0: Skipped is ranked first.
    assert days[0].stats["ranking"]["judged"] == 3
    selection_prompt = model.prompts["selection"][0]
    assert selection_prompt.index("Skipped") < selection_prompt.index("Unshown")
    assert config.weights() == {**WEIGHTS, "depth": 2.0}


def test_a_judge_config_can_decide_grey_zone_duplicates(
    sessions: sessionmaker[Session], history: dict[str, Article]
) -> None:
    config = ReplayConfig.model_validate({"deduplication": {"method": "judge"}})

    days = replay(sessions, clients(FakeModel(), FakeJudge()), since=TODAY, config=config)

    assert days[0].stats["ranking"]["method"] == "llm"
    assert days[0].stats["deduplication"]["same_day_method"] == "judge"
    assert config.thresholds() is None


def test_a_judge_config_without_a_judge_is_refused(
    sessions: sessionmaker[Session], history: dict[str, Article]
) -> None:
    config = ReplayConfig.model_validate({"ranking": {"method": "judge"}})

    with pytest.raises(ValueError, match="judge client"):
        replay(sessions, clients(FakeModel()), since=TODAY, config=config)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[ranking]\ntop_m = 20\n", "top_m"),  # misspelt: never ignored
        ("[ranking.weights]\nfit = 1.0\n", "unknown dimensions fit"),
        ('[ranking]\nmethod = "votes"\n', "'llm' or 'judge'"),
        ('[deduplication]\nmethod = "votes"\n', "'threshold' or 'judge'"),
        ("[ranking]\ntop_n = 0\n", "greater than 0"),
        ("[pool]\nexclude_sources = [0]\n", "exclude_sources"),
        ("[deduplication]\ncross_day = 0.95\n", "same_day"),
        ("[ranking\n", "Expected"),
    ],
)
def test_config_errors_name_the_problem(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "candidate.toml"
    path.write_text(text)

    with pytest.raises(ValueError, match=message):
        ReplayConfig.load(path)


def test_methods_left_out_follow_the_daily_settings() -> None:
    config = ReplayConfig.model_validate({"ranking": {"method": "judge"}})

    resolved = config.with_methods("llm", "judge")

    assert (resolved.ranking.method, resolved.deduplication.method) == ("judge", "judge")
    assert ReplayConfig().with_methods("llm", "threshold").uses_judge() is False
