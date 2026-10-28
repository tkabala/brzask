import math
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.judge import JudgeError, Judgement, Noul, NoulAnswer, Question, Text
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.db.models import EMBEDDING_DIMENSIONS
from brzask.services.digest.dedup import (
    DEFAULT_MODEL,
    MIN_SURVIVORS,
    THRESHOLDS,
    Drop,
    Thresholds,
    cosine,
    deduplicate,
    deduplicate_candidates,
    grey_pairs,
    judge_same_event,
    thresholds_for,
)
from brzask.services.digest.pool import Candidate
from tests.factories import TEST_MODEL, Factories
from tests.services.digest.fakes import NOW, context

GEMINI = THRESHOLDS["gemini-embedding-001"]


def axis(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[index] = 1.0
    return vector


def near(similarity: float, to: int, other: int) -> list[float]:
    """A unit vector at `similarity` from `axis(to)`, leaning towards `axis(other)`.

    Two vectors `near(a, to, x)` and `near(b, to, y)` with x != y have similarity a * b.
    """
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[to] = similarity
    vector[other] = math.sqrt(1 - similarity * similarity)
    return vector


def candidate(rank: int, embedding: list[float] | None, **fields: Any) -> Candidate:
    return Candidate(
        link=f"https://site{rank}.example/{rank}",
        title=f"Article {rank}",
        source_id=rank,
        source_name=f"Source {rank}",
        release=False,
        snippet=None,
        published_at=NOW,
        rank=rank,
        embedding=embedding,
        **fields,
    )


def distinct(first_rank: int, count: int) -> list[Candidate]:
    """Candidates unlike each other and anything else (each on its own axis from 100 on)."""
    return [candidate(rank, axis(100 + rank)) for rank in range(first_rank, first_rank + count)]


def ranks(candidates: list[Candidate]) -> list[int | None]:
    return [c.rank for c in candidates]


def test_cosine() -> None:
    assert cosine(axis(0), axis(0)) == pytest.approx(1.0)
    assert cosine(axis(0), axis(1)) == 0.0
    assert cosine(near(0.9, 0, 1), axis(0)) == pytest.approx(0.9)
    assert cosine([0.0] * 3, [1.0, 0.0, 0.0]) == 0.0


# --- Cross-day ---------------------------------------------------------------------------


def test_a_repeat_of_a_shown_article_is_dropped_at_the_measured_boundary() -> None:
    repeat = candidate(1, near(0.962, 0, 1))
    similar = candidate(2, near(0.959, 0, 2))
    candidates = [repeat, similar, *distinct(3, 10)]

    result = deduplicate(candidates, [axis(0)], GEMINI)

    assert result.drops == [Drop(repeat.link, "cross_day", 0.962)]
    assert ranks(result.survivors) == list(range(2, 13))


def test_the_cross_day_pass_never_goes_below_the_minimum() -> None:
    # Twelve repeats: only three may go. The closest first, then the worst ranked.
    candidates = [candidate(rank, near(0.97, 0, rank)) for rank in range(1, 11)]
    candidates.append(candidate(11, near(0.99, 0, 11)))
    candidates.append(candidate(12, near(0.98, 0, 12)))

    result = deduplicate(candidates, [axis(0)], Thresholds(0.96, (0.999,)))

    assert len(result.survivors) == MIN_SURVIVORS
    assert [drop.link.rsplit("/", 1)[-1] for drop in result.drops] == ["11", "12", "10"]


def test_no_cross_day_drops_when_the_pool_is_already_small() -> None:
    candidates = [candidate(rank, near(0.99, 0, rank)) for rank in range(1, 6)]

    result = deduplicate(candidates, [axis(0)], Thresholds(0.96, (0.999,)))

    assert result.drops == []


def test_nothing_shown_means_no_cross_day_drops() -> None:
    candidates = [candidate(1, axis(0)), *distinct(2, 10)]

    assert deduplicate(candidates, [], GEMINI).drops == []


# --- Same day -----------------------------------------------------------------------------


def test_of_two_candidates_on_one_story_the_better_ranked_stays() -> None:
    # Similarity 0.85 between them: a duplicate at the most aggressive threshold.
    better = candidate(3, near(math.sqrt(0.85), 0, 1))
    worse = candidate(2, near(math.sqrt(0.85), 0, 2))
    candidates = [*distinct(4, 10), worse, better]

    result = deduplicate(candidates, [], GEMINI)

    assert result.same_day_threshold == 0.80
    assert result.drops == [Drop(better.link, "same_day", 0.85, worse.link)]
    assert better not in result.survivors


def test_the_threshold_backs_off_until_enough_survive() -> None:
    # Ten candidates in pairs at 0.84 (duplicates at 0.80 and 0.83, not at 0.86),
    # plus two distinct ones: 0.80 would leave 7, 0.86 leaves all 12.
    pairs = []
    for pair in range(5):
        first, second = 2 * pair + 1, 2 * pair + 2
        pairs.append(candidate(first, near(math.sqrt(0.84), 10 + pair, 20 + first)))
        pairs.append(candidate(second, near(math.sqrt(0.84), 10 + pair, 20 + second)))
    candidates = [*pairs, *distinct(11, 2)]

    result = deduplicate(candidates, [], GEMINI)

    assert result.same_day_threshold == 0.86
    assert result.drops == []
    assert len(result.survivors) == 12


def test_a_day_full_of_duplicates_keeps_the_most_lenient_threshold() -> None:
    candidates = [candidate(rank, axis(0)) for rank in range(1, 13)]

    result = deduplicate(candidates, [], GEMINI)

    assert result.same_day_threshold == GEMINI.same_day[-1]
    assert ranks(result.survivors) == [1]
    assert {drop.duplicate_of for drop in result.drops} == {candidates[0].link}


def test_candidates_without_an_embedding_are_never_dropped() -> None:
    candidates = [candidate(rank, None) for rank in range(1, 4)]
    candidates += [candidate(rank, axis(0)) for rank in range(4, 7)]

    result = deduplicate(candidates, [axis(0)], GEMINI)

    assert ranks(result.survivors) == [1, 2, 3, 4]


# --- Thresholds per model --------------------------------------------------------------------


@pytest.mark.parametrize("model", ["google/gemini-embedding-001", "gemini-embedding-001"])
def test_thresholds_match_the_model_without_its_provider(model: str) -> None:
    assert thresholds_for(model) == (GEMINI, True)


def test_an_unmeasured_model_gets_the_default_thresholds() -> None:
    assert thresholds_for("nomic-embed-text") == (THRESHOLDS[DEFAULT_MODEL], False)


# --- The stage ----------------------------------------------------------------------------


def test_the_stage_compares_with_recent_articles_of_the_same_model(
    sessions: sessionmaker[Session], make: Factories
) -> None:
    today = NOW.date()
    make.article(
        embedding=axis(0),
        first_seen_at=NOW - timedelta(days=2),
        digest_date=today - timedelta(days=2),
    )
    make.article(  # other model: never compared
        embedding=axis(1),
        embedding_model="other/model",
        first_seen_at=NOW - timedelta(days=1),
        digest_date=today - timedelta(days=1),
    )
    make.article(  # too old to compare
        embedding=axis(2),
        first_seen_at=NOW - timedelta(days=8),
        digest_date=today - timedelta(days=8),
    )
    candidates = [
        candidate(1, axis(0)),
        candidate(2, axis(1)),
        candidate(3, axis(2)),
        *distinct(4, 9),
    ]
    run = context(sessions)

    survivors = deduplicate_candidates(run, candidates, TEST_MODEL).survivors

    assert ranks(survivors) == list(range(2, 13))
    stats = run.stats["deduplication"]
    assert {key: value for key, value in stats.items() if key != "drops"} == {
        "same_day_method": "threshold",
        "candidates": 12,
        "survivors": 11,
        "shown_compared": 1,
        "cross_day_dropped": 1,
        "same_day_dropped": 0,
        "same_day_threshold": 0.80,
        "judged_pairs": 0,
        "thresholds_measured": False,
    }
    assert stats["drops"] == [
        {
            "link": candidates[0].link,
            "reason": "cross_day",
            "similarity": 1.0,
            "duplicate_of": None,
            "same_event": None,
        }
    ]
    assert "deduplication" in run.timings


# --- Same-day, judged ------------------------------------------------------------------


def judged(probabilities: dict[tuple[int, int], float]) -> Any:
    """A same-event answer by rank pair; pairs not listed are 0 (different events)."""
    asked: list[list[tuple[int | None, int | None]]] = []

    def same_event(pairs: Any) -> dict[tuple[str, str], float]:
        asked.append([(a.rank, b.rank) for a, b in pairs])
        return {
            (a.link, b.link): probabilities.get((a.rank or 0, b.rank or 0), 0.0) for a, b in pairs
        }

    same_event.asked = asked  # type: ignore[attr-defined]
    return same_event


def test_grey_pairs_are_those_between_the_lowest_same_day_and_the_cross_day_threshold() -> None:
    candidates = [
        candidate(1, axis(0)),
        candidate(2, near(0.85, 0, 2)),  # grey with 1
        candidate(3, near(0.97, 0, 3)),  # above the zone with 1
        candidate(4, near(0.79, 0, 4)),  # below it
        candidate(5, None),
    ]

    pairs = grey_pairs(list(reversed(candidates)), 0.80, 0.96)

    assert [(a.rank, b.rank) for a, b in pairs] == [(1, 2), (2, 3)]  # 2-3: 0.85 * 0.97


def test_the_judge_decides_grey_pairs_and_above_the_zone_needs_no_judge() -> None:
    candidates = [
        candidate(1, axis(0)),
        candidate(2, near(0.85, 0, 2)),  # same event as 1, judged
        candidate(3, near(0.82, 0, 3)),  # same topic as 1, judged different
        candidate(4, near(0.97, 0, 4)),  # above the zone
        *distinct(5, 9),
    ]
    same_event = judged({(1, 2): 0.9, (1, 3): 0.2})

    result = deduplicate(candidates, [], GEMINI, same_event)

    assert ranks(result.survivors) == [1, 3, *range(5, 14)]
    assert result.drops == [
        Drop("https://site2.example/2", "same_day", 0.85, "https://site1.example/1", 0.9),
        Drop("https://site4.example/4", "same_day", 0.97, "https://site1.example/1", None),
    ]
    assert result.same_day_threshold is None
    assert result.judged_pairs == len(same_event.asked[0])


def on_one_site(*candidates: Candidate) -> list[Candidate]:
    return [replace(c, link=f"https://site.example/{c.rank}") for c in candidates]


def test_pairs_from_one_site_are_judged_even_above_the_zone() -> None:
    # Two articles whose embedded text is mostly the site's shared page chrome.
    first, second, third = on_one_site(
        candidate(1, axis(0)), candidate(2, near(0.97, 0, 2)), candidate(3, near(0.99, 0, 3))
    )
    candidates = [first, second, third, *distinct(4, 9)]

    pairs = grey_pairs(candidates, GEMINI.same_day[0], GEMINI.cross_day)

    assert [(a.rank, b.rank) for a, b in pairs] == [(1, 2), (1, 3), (2, 3)]


def test_the_judge_keeps_different_articles_from_one_site_above_the_zone() -> None:
    first, second, third = on_one_site(
        candidate(1, axis(0)), candidate(2, near(0.97, 0, 2)), candidate(3, near(0.99, 0, 3))
    )
    candidates = [first, second, third, *distinct(4, 9)]
    same_event = judged({(1, 2): 0.1, (1, 3): 0.9, (2, 3): 0.1})

    result = deduplicate(candidates, [], GEMINI, same_event)

    assert result.drops == [Drop(third.link, "same_day", 0.99, first.link, 0.9)]


def test_an_undecided_judge_keeps_both() -> None:
    candidates = [candidate(1, axis(0)), candidate(2, near(0.85, 0, 2)), *distinct(3, 9)]

    result = deduplicate(candidates, [], GEMINI, judged({(1, 2): 0.49}))

    assert result.drops == []


def test_the_judged_pass_keeps_the_survivor_floor() -> None:
    # Every pair at 0.99 * 0.99 = 0.98, above the zone.
    candidates = [candidate(rank, near(0.99, 0, rank)) for rank in range(1, 12)]

    result = deduplicate(candidates, [], GEMINI, judged({}))

    assert len(result.survivors) == MIN_SURVIVORS
    assert ranks(result.survivors) == list(range(1, 10))  # equally close: the worst ranked go


def test_when_the_floor_binds_the_closest_duplicates_go_first() -> None:
    candidates = [
        candidate(1, axis(0)),
        candidate(2, near(0.85, 0, 2)),  # grey, judged the same event as 1
        *distinct(3, 7),
        candidate(10, near(0.99, 0, 10)),  # near-identical to 1, ranked last
    ]

    result = deduplicate(candidates, [], GEMINI, judged({(1, 2): 0.6}))

    assert len(result.survivors) == MIN_SURVIVORS
    assert [drop.link for drop in result.drops] == ["https://site10.example/10"]


def test_without_grey_pairs_the_judge_is_not_asked() -> None:
    same_event = judged({})

    deduplicate(distinct(1, 10), [], GEMINI, same_event)

    assert same_event.asked == []


class PairJudge:
    """Says every pair is one event with probability 0.8; keeps the request."""

    model = "test/judge"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[tuple[Any, dict[str, Question]]] = []

    def ask(
        self,
        state: Text,
        questions: Any,
        *,
        purpose: str,
        meter: UsageMeter | None = None,
    ) -> Judgement:
        self.requests.append((state, dict(questions)))
        if self.fail:
            raise JudgeError("unavailable")
        usage = CallUsage(self.model, purpose, 300, 0, 0.00001, 1)
        if meter is not None:
            meter.add(usage)
        return Judgement({name: NoulAnswer(0.8) for name in questions}, usage)

    def close(self) -> None:
        pass


def test_pairs_are_asked_in_one_call_with_each_article_once() -> None:
    judge = PairJudge()
    first = candidate(1, axis(0), text="A long text " * 200)
    second = replace(candidate(2, near(0.85, 0, 2)), snippet="Only a snippet")
    third = candidate(3, near(0.85, 0, 3))

    answers = judge_same_event(judge)([(first, second), (first, third)])

    assert answers == {(first.link, second.link): 0.8, (first.link, third.link): 0.8}
    ((state, questions),) = judge.requests
    assert list(state["articles"]) == ["a1", "a2", "a3"]
    assert len(state["articles"]["a1"]["text"]) == 1000
    assert state["articles"]["a2"]["text"] == "Only a snippet"
    question = questions["pair1"]
    assert isinstance(question, Noul)
    assert question.instructions == "Do `articles.a1` and `articles.a3` report the same event?"


def test_the_stage_uses_the_judge_and_falls_back_when_it_fails(
    sessions: sessionmaker[Session],
) -> None:
    candidates = [candidate(1, axis(0)), candidate(2, near(0.85, 0, 2)), *distinct(3, 9)]

    run = context(sessions)
    survivors = deduplicate_candidates(run, candidates, TEST_MODEL, judge=PairJudge()).survivors
    assert len(survivors) == 10
    assert run.stats["deduplication"]["same_day_method"] == "judge"
    assert run.stats["deduplication"]["judged_pairs"] == 1
    assert run.stats["deduplication"]["drops"][0]["same_event"] == 0.8
    assert run.usage.summary()["by_purpose"]["deduplication"]["calls"] == 1

    run = context(sessions)
    survivors = deduplicate_candidates(
        run, candidates, TEST_MODEL, judge=PairJudge(fail=True)
    ).survivors
    assert len(survivors) == 10  # the 0.80 threshold drops the pair too
    assert run.stats["deduplication"]["same_day_method"] == "threshold (judge failed)"
