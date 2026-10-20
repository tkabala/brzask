"""Ranking by composite score: each candidate judged on several dimensions, combined in code.

The alternative to the LLM's ranking (`DIGEST_RANKING=judge`). A judge
answers narrow questions about one article at a time: how well it fits the
interests, how new it is, how much substance it promises, how promotional it
is, how close it is to what the reader opened. Each answer is a level on a
scale; the weights below turn them into one number. The answers mean the same
whatever the weights, so other weights can be tried with `brzask replay`
without asking again for every combination.

Ranking happens before extraction, so the judge sees the title and the feed
snippet, as the LLM ranking does.
"""

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from brzask.clients.judge import Judge, JudgeError, Score, ScoreAnswer
from brzask.clients.usage import UsageMeter
from brzask.log import get_logger
from brzask.services.digest.pool import Candidate

log = get_logger(__name__)

# Articles judged at once; each call takes well under a second.
JUDGE_WORKERS = 8
# Characters of the snippet the judge sees, as many as the ranking prompt shows.
SNIPPET_CHARS = 300

DIMENSIONS: Mapping[str, Score] = {
    "interest_fit": Score(
        "How well does `article` match the reader's interests in `reader.interests`? "
        "An interest's notes are the reader's own words and outrank its keywords.",
        [
            "Matches none of the interests",
            "Matches an interest, but it is something that interest's notes say to skip",
            "Touches an interest only in passing",
            "Clearly about an interest, neither wanted nor skipped by its notes",
            "Exactly what an interest's notes say the reader wants",
        ],
    ),
    "novelty": Score(
        "How much does `article` bring that is genuinely new? For release notes "
        "(`article.release_notes`), judge what the release changes, not that a version shipped.",
        [
            "Nothing new: a routine version bump, a patch release, a rehash or a roundup",
            "Small news: an incremental change or a minor update",
            "Real news: a new feature, finding, result or event worth knowing about",
        ],
    ),
    "depth": Score(
        "How much substance does `article` promise, judging by its title and snippet?",
        [
            "A headline, a link or a teaser with nothing to read",
            "A short report of what happened",
            "An in-depth piece: analysis, explanation, measurements or a detailed write-up",
        ],
    ),
    "promotion": Score(
        "How promotional is `article`?",
        [
            "Independent reporting, analysis or a project's own technical notes",
            "Written by a vendor about its product, but informative",
            "Mostly a sales pitch, an advertisement or an event or webinar invitation",
        ],
    ),
    "opened_similarity": Score(
        "How close is `article` to the articles the reader opened recently "
        "(`reader.recently_opened`), in topic and kind?",
        [
            "Unlike anything the reader opened",
            "Shares a broad topic with something the reader opened",
            "Very much like articles the reader opened",
        ],
    ),
}

# Hand-set, not measured: interest fit leads, what the reader opens only nudges
# (as in the LLM ranking), and promotion counts against. Compare others with
# `brzask replay` ([ranking.weights]).
WEIGHTS: Mapping[str, float] = {
    "interest_fit": 1.0,
    "novelty": 0.5,
    "depth": 0.3,
    "promotion": -0.5,
    "opened_similarity": 0.2,
}


@dataclass(frozen=True, slots=True)
class Scored:
    position: int  # in the pool
    answers: Mapping[str, ScoreAnswer]

    def composite(self, weights: Mapping[str, float]) -> float:
        """Weighted sum of each dimension's score scaled to 0..1."""
        return weighted({name: scaled(answer) for name, answer in self.answers.items()}, weights)


def judge_state(
    candidate: Candidate,
    interests: Sequence[Mapping[str, Any]],
    opened_titles: Sequence[str],
) -> dict[str, Any]:
    """What the judge reads about one candidate."""
    snippet = (candidate.snippet or "")[:SNIPPET_CHARS]
    return {
        "reader": {
            "interests": [dict(interest) for interest in interests],
            "recently_opened": list(opened_titles),
        },
        "article": {
            "source": candidate.source_name,
            "title": candidate.title,
            "snippet": snippet,
            "release_notes": candidate.release,
        },
    }


def score_candidates(
    candidates: Sequence[Candidate],
    judge: Judge,
    interests: Sequence[Mapping[str, Any]],
    opened_titles: Sequence[str],
    *,
    meter: UsageMeter | None = None,
    workers: int = JUDGE_WORKERS,
) -> list[Scored]:
    """Every candidate's answers, in pool order.

    A candidate whose call fails is left out and ranks after the judged ones;
    when no call succeeds, the judge is unusable and the last error is raised.
    """

    def judge_one(position: int) -> Scored | JudgeError:
        state = judge_state(candidates[position], interests, opened_titles)
        try:
            judgement = judge.ask(state, DIMENSIONS, purpose="ranking", meter=meter)
        except JudgeError as error:
            log.warning("candidate not judged", link=candidates[position].link, error=str(error))
            return error
        return Scored(position, {name: judgement.score(name) for name in DIMENSIONS})

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(judge_one, range(len(candidates))))
    scored = [result for result in results if isinstance(result, Scored)]
    errors = [result for result in results if isinstance(result, JudgeError)]
    if errors and not scored:
        raise errors[-1]
    return scored


def composite_ranking(scored: Sequence[Scored], weights: Mapping[str, float]) -> list[int]:
    """Pool positions, best composite first; equal scores keep pool order."""
    ordered = sorted(scored, key=lambda item: (-item.composite(weights), item.position))
    return [item.position for item in ordered]


def scaled(answer: ScoreAnswer) -> float:
    """The answer's score scaled to 0..1."""
    return answer.score / (len(answer.probabilities) - 1)


def weighted(scores: Mapping[str, float], weights: Mapping[str, float]) -> float:
    """Weighted sum of scaled scores; a dimension without a score counts as 0."""
    return sum(weight * scores.get(name, 0.0) for name, weight in weights.items())
