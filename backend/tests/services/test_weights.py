import json
import random
from datetime import date, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from brzask.cli import app
from brzask.services.digest.scoring import DIMENSIONS
from brzask.services.weights import Example, evaluate, examples_from_bench, fit

START = date(2026, 10, 1)


def synthetic(count: int = 300, seed: int = 1) -> list[Example]:
    """Opens driven by promotion (against) and depth (for); the rest is noise."""
    rng = random.Random(seed)
    examples = []
    for index in range(count):
        scores = {name: rng.random() for name in DIMENSIONS}
        chance = 0.02 + 0.9 * scores["depth"] * (1 - scores["promotion"]) ** 2
        examples.append(Example(START + timedelta(days=index % 10), scores, rng.random() < chance))
    return examples


def test_fit_finds_the_signs_of_what_drives_opens() -> None:
    weights = fit(synthetic())

    assert set(weights) == set(DIMENSIONS)
    assert weights["depth"] > 0.5
    assert weights["promotion"] < -0.5
    noise = ("interest_fit", "novelty", "opened_similarity")
    assert all(abs(weights[name]) < abs(weights["depth"]) for name in noise)


def test_a_larger_penalty_shrinks_the_weights() -> None:
    loose, tight = fit(synthetic(), l2=0.001), fit(synthetic(), l2=1.0)

    assert sum(map(abs, tight.values())) < sum(map(abs, loose.values()))


def test_learned_weights_beat_weights_that_ignore_the_signal_out_of_sample() -> None:
    blind = {"interest_fit": 1.0}  # pure noise in the synthetic data

    result = evaluate(synthetic(), hand=blind)

    assert result.days == 10
    assert result.learned_auc is not None and result.hand_auc is not None
    assert result.learned_auc > 0.7 > 0.6 > result.hand_auc


def test_nothing_to_fit_is_an_error() -> None:
    with pytest.raises(ValueError, match="nothing"):
        fit([])


def bench_report() -> dict[str, object]:
    rows = [
        {
            "day": (START + timedelta(days=index % 3)).isoformat(),
            "article_id": index,
            "title": f"A{index}",
            "opened": example.opened,
            "scores": dict(example.scores),
        }
        for index, example in enumerate(synthetic(60))
    ]
    return {"models": [{"model": "test/judge", "rows": rows}]}


def test_examples_come_from_the_named_model_of_a_bench_report() -> None:
    examples = examples_from_bench(bench_report(), "test/judge")

    assert len(examples) == 60
    assert examples[0].day == START
    with pytest.raises(ValueError, match="has: test/judge"):
        examples_from_bench(bench_report(), "other/model")


def test_the_command_prints_weights_for_a_replay_config(tmp_path: Path) -> None:
    path = tmp_path / "bench.json"
    path.write_text(json.dumps(bench_report()))

    result = CliRunner().invoke(app, ["fit-weights", str(path), "--until", "2026-10-02"])

    assert result.exit_code == 0, result.output
    assert "Leave-one-day-out AUC over 2 days, 40 articles" in result.output
    assert "[ranking.weights]\ninterest_fit = " in result.output
