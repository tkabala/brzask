from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.llm import Completion, InvalidJSONError
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.db.models import Article
from brzask.repositories.articles import OpenedArticle
from brzask.services.digest.pool import Candidate
from brzask.services.digest.ranking import (
    MIN_CANDIDATES,
    OPENED_TITLES,
    RANK_LIMIT,
    TOP_N,
    RankingLimits,
    parse_ranking,
    rank_candidates,
    ranking_prompt,
    select_top,
)
from tests.factories import Factories
from tests.services.digest.fakes import NOW, context


def candidate(n: int, source_id: int | None = None, **fields: Any) -> Candidate:
    """Candidate `n`, from its own source unless `source_id` says otherwise."""
    source = n if source_id is None else source_id
    defaults: dict[str, Any] = {
        "link": f"https://news.example/{n}",
        "release": False,
        "snippet": None,
        "published_at": NOW,
    }
    return Candidate(
        title=f"Article {n}",
        source_id=source,
        source_name=f"Source {source}",
        **(defaults | fields),
    )


def titles(candidates: Sequence[Candidate]) -> list[str]:
    return [c.title for c in candidates]


# --- Parsing the answer --------------------------------------------------------------


def test_parse_ranking_turns_ids_into_pool_positions() -> None:
    assert parse_ranking({"ranking": [3, 1, 2]}, 3) == [2, 0, 1]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ({"ranking": [2, 2, 1, 2]}, [1, 0]),  # repeated IDs
        ({"ranking": [0, 4, -1, 3, 99]}, [2]),  # out of range
        ({"ranking": ["2", 1.0, 3.5, True, None, "x", [1]]}, [1, 0]),  # odd types
        ({"ranking": []}, []),
        ({"ranking": "1, 2"}, []),
        ({"order": [1, 2]}, []),  # missing key
        ([1, 2, 3], []),  # not an object
        (None, []),
    ],
)
def test_parse_ranking_skips_what_it_cannot_use(answer: Any, expected: list[int]) -> None:
    assert parse_ranking(answer, 3) == expected


# --- Picking the top -------------------------------------------------------------------


def test_other_limits_can_be_tried() -> None:
    pool = [candidate(n, source_id=n % 3) for n in range(1, 31)]
    limits = RankingLimits(rank_limit=20, top_n=6, max_per_source=1, min_candidates=4)

    top = select_top(pool, list(range(30)), limits)

    assert titles(top) == ["Article 1", "Article 2", "Article 3", "Article 4"]
    assert "best 20 candidates" in ranking_prompt(pool, [], [], limits.rank_limit)


def test_top_follows_the_ranking_and_numbers_the_ranks() -> None:
    pool = [candidate(n) for n in range(1, 21)]

    top = select_top(pool, [4, 0, 9])

    assert titles(top[:3]) == ["Article 5", "Article 1", "Article 10"]
    assert [c.rank for c in top[:3]] == [1, 2, 3]
    # The rest of the pool tops the list up to the minimum, in pool order.
    assert len(top) == MIN_CANDIDATES
    assert titles(top[3:5]) == ["Article 2", "Article 3"]
    assert top[3].rank == 4


def test_top_stops_at_top_n() -> None:
    pool = [candidate(n) for n in range(1, 41)]

    top = select_top(pool, list(range(40)))

    assert len(top) == TOP_N
    assert top[-1].rank == TOP_N


def test_a_source_gets_at_most_two_places_while_others_are_left() -> None:
    chatty = [candidate(n, source_id=1) for n in range(1, 6)]
    others = [candidate(n) for n in range(6, 30)]
    pool = [*chatty, *others]

    top = select_top(pool, list(range(len(pool))))

    assert titles(top[:3]) == ["Article 1", "Article 2", "Article 6"]
    assert sum(c.source_id == 1 for c in top) == 2
    assert len(top) == TOP_N
    # Ranks stay the model's positions, with gaps where articles were skipped.
    assert [c.rank for c in top[:3]] == [1, 2, 6]


def test_the_source_limit_is_lifted_on_a_day_with_few_sources() -> None:
    pool = [candidate(n, source_id=1 + n % 3) for n in range(1, 13)]  # three sources

    top = select_top(pool, list(range(len(pool))))

    assert len(top) == MIN_CANDIDATES
    assert [c.rank for c in top] == list(range(1, MIN_CANDIDATES + 1))


def test_without_a_ranking_the_pool_order_is_used() -> None:
    pool = [candidate(n, source_id=1 + n % 2) for n in range(1, 13)]

    top = select_top(pool, [])

    assert titles(top) == [f"Article {n}" for n in range(1, MIN_CANDIDATES + 1)]


def test_a_small_pool_is_taken_whole() -> None:
    pool = [candidate(n, source_id=1) for n in range(1, 4)]

    assert titles(select_top(pool, [2])) == ["Article 3", "Article 1", "Article 2"]
    assert select_top([], []) == []


# --- The prompt ---------------------------------------------------------------------------


def test_prompt_numbers_candidates_by_pool_position_and_summarises_opens() -> None:
    pool = [candidate(1, release=True, snippet="Notes"), candidate(2, article_id=77)]
    opens = [
        OpenedArticle(f"Opened {n}", "Postgres" if n % 2 else "Rust", "Lobsters", NOW)
        for n in range(OPENED_TITLES + 5)
    ]

    text = ranking_prompt(pool, [{"topic": "Rust", "keywords": [], "notes": ""}], opens)

    assert "1. [RELEASE] [Source 1] Article 1\n   Notes\n" in text
    assert "2. [Source 2] Article 2\n" in text
    assert "77." not in text
    assert f"- Opened {OPENED_TITLES - 1}\n" in text
    assert f"- Opened {OPENED_TITLES}\n" not in text
    assert "- Rust (10)" in text
    assert "- Lobsters (20)" in text
    assert "Return the ids of the best 2 candidates" in text


def test_prompt_asks_for_at_most_the_rank_limit() -> None:
    pool = [candidate(n) for n in range(RANK_LIMIT + 10)]

    assert f"best {RANK_LIMIT} candidates" in ranking_prompt(pool, [], [])


# --- The stage ---------------------------------------------------------------------------


class FakeModel:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def complete_json(
        self, prompt: str, *, purpose: str, meter: UsageMeter | None = None
    ) -> tuple[Any, Completion]:
        self.prompts.append(prompt)
        usage = CallUsage("test/model", purpose, 1000, 50, 0.001, 1)
        if meter is not None:
            meter.add(usage)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer, Completion("{}", usage)


def stored_pool(make: Factories, size: int) -> list[Candidate]:
    pool = []
    for n in range(1, size + 1):
        source = make.source()
        article = make.article(source)
        pool.append(candidate(n, source_id=source.id, article_id=article.id, link=article.link))
    return pool


def test_rank_candidates_stores_the_ranks_of_the_top(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    make.interest("Postgres", notes="skip: vendor webinars")
    make.interest("Gardening", active=False)
    opened = make.article(title="Why we left Kafka", opened_at=NOW - timedelta(days=3))
    make.article(title="Too old to count", opened_at=NOW - timedelta(days=120))
    pool = stored_pool(make, 12)
    model = FakeModel({"ranking": [3, 1]})
    run = context(sessions)

    top = rank_candidates(run, pool, model)

    assert [c.rank for c in top[:2]] == [1, 2]
    assert titles(top[:2]) == ["Article 3", "Article 1"]
    assert len(top) == MIN_CANDIDATES
    session.expire_all()
    ranks = {c.article_id: session.get_one(Article, c.article_id).rank for c in pool}
    assert ranks[pool[2].article_id] == 1
    assert ranks[pool[0].article_id] == 2
    assert sum(rank is not None for rank in ranks.values()) == MIN_CANDIDATES
    prompt = model.prompts[0]
    assert "[reader note: skip: vendor webinars]" in prompt
    assert "Gardening" not in prompt
    assert f"- {opened.title}\n" in prompt
    assert "Too old to count" not in prompt
    assert run.usage.summary()["calls"] == 1
    assert run.stats["ranking"] == {
        "prompt_chars": len(prompt),
        "ranked": 2,
        "top": MIN_CANDIDATES,
        "top_ranked": 2,
        "sources": MIN_CANDIDATES,
    }
    assert "ranking" in run.timings


def test_a_dry_run_stores_no_ranks(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    pool = [*stored_pool(make, 2), candidate(3)]  # the fresh one has no article ID

    top = rank_candidates(context(sessions, dry_run=True), pool, FakeModel({"ranking": [3]}))

    assert titles(top) == ["Article 3", "Article 1", "Article 2"]
    session.expire_all()
    assert all(session.get_one(Article, c.article_id).rank is None for c in pool[:2])


def test_an_answer_that_is_not_json_falls_back_to_pool_order(
    sessions: sessionmaker[Session], make: Factories
) -> None:
    pool = stored_pool(make, 3)
    run = context(sessions)

    top = rank_candidates(run, pool, FakeModel(InvalidJSONError("I think article 2")))

    assert titles(top) == ["Article 1", "Article 2", "Article 3"]
    assert run.stats["ranking"]["ranked"] == 0


def test_an_empty_pool_asks_nothing(sessions: sessionmaker[Session]) -> None:
    model = FakeModel({"ranking": []})

    assert rank_candidates(context(sessions), [], model) == []
    assert model.prompts == []
