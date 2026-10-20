from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.judge import JudgeError, ScoreAnswer
from brzask.db.models import Article
from brzask.services.digest.ranking import rank_candidates
from brzask.services.digest.scoring import (
    DIMENSIONS,
    SNIPPET_CHARS,
    WEIGHTS,
    Scored,
    composite_ranking,
    judge_state,
    score_candidates,
)
from tests.factories import Factories
from tests.services.digest.fakes import NOW, FakeJudge, context
from tests.services.digest.test_ranking import FakeModel, candidate, stored_pool, titles


def scored(position: int, **levels: int) -> Scored:
    """Sure answers at `levels` (0 for dimensions left out)."""
    answers = {}
    for name, question in DIMENSIONS.items():
        level = levels.get(name, 0)
        count = len(question.levels)
        answers[name] = ScoreAnswer(
            float(level), tuple(float(i == level) for i in range(count)), 1.0
        )
    return Scored(position, answers)


# --- Combining scores ----------------------------------------------------------------


def test_composite_scales_each_dimension_to_one_before_weighting() -> None:
    top = scored(0, interest_fit=4, novelty=2, depth=2, promotion=0, opened_similarity=2)
    worst = scored(1, promotion=2)

    assert top.composite(WEIGHTS) == pytest.approx(1.0 + 0.5 + 0.3 + 0.2)
    assert worst.composite(WEIGHTS) == pytest.approx(-0.5)
    assert scored(2, interest_fit=2).composite({"interest_fit": 2.0}) == pytest.approx(1.0)


def test_ranking_orders_by_composite_and_keeps_pool_order_on_ties() -> None:
    items = [
        scored(0, interest_fit=1),
        scored(1, interest_fit=4, promotion=2),
        scored(2, interest_fit=4),
        scored(3, interest_fit=1),
    ]

    assert composite_ranking(items, WEIGHTS) == [2, 1, 0, 3]
    assert composite_ranking(items, {"promotion": -1.0}) == [0, 2, 3, 1]


def test_every_dimension_has_a_weight_and_at_least_three_levels() -> None:
    assert set(WEIGHTS) == set(DIMENSIONS)
    assert all(len(question.levels) >= 3 for question in DIMENSIONS.values())


# --- What the judge sees ---------------------------------------------------------------


def test_state_has_the_reader_and_the_article() -> None:
    interests = [{"topic": "Postgres", "keywords": ["pgvector"], "notes": "skip: webinars"}]
    item = candidate(1, snippet="x" * 1000, release=True)

    state = judge_state(item, interests, ["Why we left Kafka"])

    assert state == {
        "reader": {"interests": interests, "recently_opened": ["Why we left Kafka"]},
        "article": {
            "source": "Source 1",
            "title": "Article 1",
            "snippet": "x" * SNIPPET_CHARS,
            "release_notes": True,
        },
    }


def test_failed_candidates_are_left_out() -> None:
    judge = FakeJudge({"Article 2": {"interest_fit": 3}}, fail={"Article 1"})
    pool = [candidate(1), candidate(2), candidate(3)]

    result = score_candidates(pool, judge, [], [], workers=2)

    assert [item.position for item in result] == [1, 2]
    assert result[0].answers["interest_fit"].score == 3


def test_when_every_call_fails_the_error_is_raised() -> None:
    judge = FakeJudge(fail={"Article 1", "Article 2"})

    with pytest.raises(JudgeError, match="failed for"):
        score_candidates([candidate(1), candidate(2)], judge, [], [])


# --- The ranking stage with a judge ------------------------------------------------------


def test_rank_candidates_with_a_judge_orders_by_composite(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    make.interest("Postgres", notes="skip: vendor webinars")
    opened = make.article(title="Why we left Kafka", opened_at=NOW - timedelta(days=3))
    pool = stored_pool(make, 12)
    judge = FakeJudge(
        {
            "Article 5": {"interest_fit": 4, "novelty": 2},
            "Article 9": {"interest_fit": 4, "promotion": 2},
            "Article 2": {"interest_fit": 3},
        },
        fail={"Article 12"},
    )
    model = FakeModel({"ranking": [1]})
    run = context(sessions)

    top = rank_candidates(run, pool, model, judge=judge)

    assert titles(top[:3]) == ["Article 5", "Article 2", "Article 9"]
    assert [c.rank for c in top[:3]] == [1, 2, 3]
    assert len(top) == 11  # every judged one; the failed one is not needed
    assert model.prompts == []  # the LLM is not asked
    state: dict[str, Any] = judge.states[0]
    assert state["reader"]["interests"][0]["notes"] == "skip: vendor webinars"
    assert state["reader"]["recently_opened"] == [opened.title]
    assert run.stats["ranking"] == {
        "method": "judge",
        "judge_model": "test/judge",
        "judged": 11,
        "ranked": 11,
        "top": 11,
        "top_ranked": 11,
        "sources": 11,
    }
    assert run.usage.summary()["by_purpose"]["ranking"]["calls"] == 11
    session.expire_all()
    assert session.get_one(Article, pool[4].article_id).rank == 1


def test_weights_change_the_order_without_asking_differently(
    sessions: sessionmaker[Session], make: Factories
) -> None:
    pool = stored_pool(make, 3)
    judge = FakeJudge({"Article 1": {"interest_fit": 4}, "Article 3": {"depth": 2}})

    top = rank_candidates(
        context(sessions, dry_run=True), pool, FakeModel({}), judge=judge, weights={"depth": 1.0}
    )

    assert titles(top) == ["Article 3", "Article 1", "Article 2"]


def test_when_the_judge_fails_on_every_candidate_the_llm_ranks(
    sessions: sessionmaker[Session], make: Factories
) -> None:
    pool = stored_pool(make, 3)
    judge = FakeJudge(fail={"Article 1", "Article 2", "Article 3"})
    model = FakeModel({"ranking": [3]})
    run = context(sessions, dry_run=True)

    top = rank_candidates(run, pool, model, judge=judge)

    assert titles(top) == ["Article 3", "Article 1", "Article 2"]
    assert len(model.prompts) == 1
    assert run.stats["ranking"]["method"] == "llm (judge failed)"
