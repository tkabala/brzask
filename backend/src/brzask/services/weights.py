"""Composite weights learned from opens.

Each shown article's judged scores (see `judge_bench`) are features and
whether it was opened is the label; a logistic regression with an L2 penalty
fits one weight per dimension. Only the order of articles matters for
ranking, so the intercept is dropped and the weights go to the composite as
they are.

Learned weights are compared with the hand-set ones out of sample: each day
is scored with weights fitted on the other days (leave one day out), and the
pooled scores give one AUC per set of weights.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from brzask.services.digest import scoring
from brzask.services.judge_bench import auc

# Penalty on the squared weights, added to the mean log loss. Not tuned: with
# about 20 opened articles it keeps weights small rather than chasing single
# articles.
L2 = 0.01
# Plain gradient descent on a convex loss. With features in 0..1 a step of 1
# stays stable; on 195 judged articles the weights settle to 0.001 by about
# 1000 iterations and stop changing at 3000.
STEP = 1.0
ITERATIONS = 1500


@dataclass(frozen=True, slots=True)
class Example:
    day: date
    scores: Mapping[str, float]  # by dimension, scaled to 0..1
    opened: bool


@dataclass(frozen=True, slots=True)
class Evaluation:
    learned: dict[str, float]  # fitted on every example
    learned_auc: float | None  # leave one day out
    hand_auc: float | None
    days: int
    examples: int
    opened: int


def examples_from_bench(report: Mapping[str, Any], model: str | None = None) -> list[Example]:
    """The rows of one model in a `brzask judge-bench --json` report (the first if not named)."""
    models = report.get("models") or []
    chosen = next((entry for entry in models if model is None or entry.get("model") == model), None)
    if chosen is None:
        names = ", ".join(str(entry.get("model")) for entry in models)
        raise ValueError(f"no model {model!r} in the report (it has: {names or 'none'})")
    return [
        Example(
            day=date.fromisoformat(row["day"]),
            scores={name: float(row["scores"][name]) for name in scoring.DIMENSIONS},
            opened=bool(row["opened"]),
        )
        for row in chosen["rows"]
    ]


def fit(
    examples: Sequence[Example],
    l2: float = L2,
    step: float = STEP,
    iterations: int = ITERATIONS,
) -> dict[str, float]:
    """Logistic regression weights per dimension, by gradient descent on the mean log loss."""
    if not examples:
        raise ValueError("nothing to fit")
    names = list(scoring.DIMENSIONS)
    rows = [[example.scores[name] for name in names] for example in examples]
    labels = [1.0 if example.opened else 0.0 for example in examples]
    weights = [0.0] * len(names)
    bias = 0.0
    count = len(rows)
    for _ in range(iterations):
        gradient = [0.0] * len(names)
        gradient_bias = 0.0
        for row, label in zip(rows, labels, strict=True):
            error = _sigmoid(bias + sum(w * x for w, x in zip(weights, row, strict=True))) - label
            gradient_bias += error
            for index, value in enumerate(row):
                gradient[index] += error * value
        bias -= step * gradient_bias / count
        weights = [w - step * (g / count + l2 * w) for w, g in zip(weights, gradient, strict=True)]
    return {name: round(weight, 4) for name, weight in zip(names, weights, strict=True)}


def evaluate(
    examples: Sequence[Example],
    hand: Mapping[str, float] = scoring.WEIGHTS,
    l2: float = L2,
) -> Evaluation:
    """Learned weights against `hand`, both scored on days the learned ones were not fitted on."""
    days = sorted({example.day for example in examples})
    learned_scores: list[float] = []
    hand_scores: list[float] = []
    labels: list[bool] = []
    for day in days:
        held_out = [example for example in examples if example.day == day]
        training = [example for example in examples if example.day != day]
        if not training:
            continue
        weights = fit(training, l2)
        for example in held_out:
            learned_scores.append(scoring.weighted(example.scores, weights))
            hand_scores.append(scoring.weighted(example.scores, hand))
            labels.append(example.opened)
    return Evaluation(
        learned=fit(examples, l2),
        learned_auc=auc(learned_scores, labels) if labels else None,
        hand_auc=auc(hand_scores, labels) if labels else None,
        days=len(days),
        examples=len(examples),
        opened=sum(example.opened for example in examples),
    )


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exp = math.exp(value)  # no overflow for large negative values
    return exp / (1 + exp)
