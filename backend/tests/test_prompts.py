import json
import re
from pathlib import Path
from typing import Any

import jinja2
import pytest

from brzask import prompts

INTERESTS = [
    {
        "topic": "Postgres",
        "keywords": ["pgvector", "replication"],
        "notes": "skip: vendor webinars",
    },
    {"topic": "Rust", "keywords": [], "notes": ""},
]

SAMPLES: dict[str, dict[str, Any]] = {
    "ranking": {
        "interests": INTERESTS,
        "opened_titles": ["Postgres 18 released", "Why we left Kafka"],
        "opened_topics": [{"name": "Postgres", "count": 3}],
        "opened_sources": [{"name": "Lobsters", "count": 2}],
        "candidates": [
            {
                "id": 11,
                "source": "PG Weekly",
                "title": "Async I/O",
                "snippet": "Deep dive. " * 60,
                "release": False,
            },
            {
                "id": 12,
                "source": "github.com/a/b",
                "title": "v2.0.0",
                "snippet": "",
                "release": True,
            },
        ],
        "rank_limit": 40,
    },
    "judge": {
        "state": '{"article": {"title": "Postgres 18 released"}}',
        "questions": [
            {
                "name": "is_release",
                "kind": "noul",
                "instructions": "Is `article` a release announcement?",
                "criteria": None,
                "options": [],
                "levels": [],
            },
            {
                "name": "kind",
                "kind": "choice",
                "instructions": "What kind of article is it?",
                "criteria": '{"release": "A new version", "news": "Anything else"}',
                "options": ["release", "news"],
                "levels": [],
            },
            {
                "name": "fit",
                "kind": "score",
                "instructions": "How well does it fit Postgres?",
                "criteria": None,
                "options": ["0", "1", "2"],
                "levels": ["Unrelated", "Related", "Exactly"],
            },
        ],
    },
    "selection": {
        "interests": INTERESTS,
        "candidates": [
            {
                "title": "Async I/O in Postgres 18",
                "link": "https://pg.example/async",
                "source": "PG Weekly",
                "published": "2026-10-16",
                "rank": 1,
                "release": False,
                "text": "Postgres 18 can issue reads asynchronously.",
            },
            {
                "title": "Rust 1.95",
                "link": "https://rust.example/1.95",
                "source": "Rust Blog",
                "published": None,
                "rank": 2,
                "release": True,
                "text": "",
            },
        ],
        "digest_size": 7,
        "language": prompts.language("pl"),
    },
    "web_search": {"query": "blogs about Postgres internals", "limit": 10},
    "discovery_search": {
        "topic": "Postgres",
        "keywords": ["pgvector", "replication"],
        "conversational": True,
    },
}


def test_every_prompt_has_sample_data() -> None:
    assert sorted(SAMPLES) == prompts.names()


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_prompts_render_cleanly(name: str) -> None:
    text = prompts.render(name, **SAMPLES[name])

    assert "{{" not in text and "{%" not in text and "{#" not in text
    assert "\n\n\n" not in text
    assert text == text.strip() + "\n"
    assert not re.search(r"[ \t]+\n", text), "trailing whitespace"


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_a_missing_variable_is_an_error(name: str) -> None:
    context = dict(SAMPLES[name])
    context.pop(next(iter(context)))

    with pytest.raises(jinja2.UndefinedError):
        prompts.render(name, **context)


def test_interests_put_reader_notes_after_keywords() -> None:
    text = prompts.render("ranking", **SAMPLES["ranking"])

    assert "- Postgres: pgvector, replication [reader note: skip: vendor webinars]\n" in text
    assert "- Rust\n" in text


def test_no_interests() -> None:
    text = prompts.render("ranking", **{**SAMPLES["ranking"], "interests": []})

    assert "(no interests configured" in text


def test_ranking_lists_candidates_and_the_schema() -> None:
    text = prompts.render("ranking", **SAMPLES["ranking"])

    assert "11. [PG Weekly] Async I/O\n" in text
    assert "12. [RELEASE] [github.com/a/b] v2.0.0\n" in text
    assert "Return the ids of the best 40 candidates" in text
    assert '{"ranking": [id, id, ...]}' in text
    snippet_line = next(line for line in text.splitlines() if line.startswith("   Deep dive."))
    assert len(snippet_line.strip()) <= 300
    assert "- Postgres (3)" in text
    assert "Below are 2 candidate articles." in text


def test_ranking_without_opens() -> None:
    sample = {**SAMPLES["ranking"], "opened_titles": [], "opened_topics": [], "opened_sources": []}

    assert prompts.render("ranking", **sample).count("(none yet)") == 3


def test_selection_asks_for_the_digest_language() -> None:
    text = prompts.render("selection", **SAMPLES["selection"])

    assert '"title": the headline in Polish' in text
    assert '"summary": 2-3 sentences in Polish.' in text
    assert 'if none fits, "Ogólne"' in text
    assert "1. [Async I/O in Postgres 18](https://pg.example/async)" in text
    assert "Published: unknown" in text
    assert "select exactly 7 articles" in text


def test_selection_in_english() -> None:
    text = prompts.render(
        "selection", **{**SAMPLES["selection"], "language": prompts.language("en")}
    )

    assert "the headline in English" in text
    assert 'if none fits, "General"' in text


def test_web_search() -> None:
    text = prompts.render("web_search", **SAMPLES["web_search"])

    assert text.startswith("Search the web for: blogs about Postgres internals\n")
    assert "List up to 10 of" in text


def test_languages() -> None:
    assert prompts.language("en").name == "English"
    with pytest.raises(ValueError, match="unsupported digest language 'de'"):
        prompts.language("de")


def test_values_are_not_escaped() -> None:
    sample = {**SAMPLES["web_search"], "query": 'C++ & "Rust" <generics>'}

    assert 'C++ & "Rust" <generics>' in prompts.render("web_search", **sample)


def test_json_examples_are_valid_shapes() -> None:
    # The selection schema line is shown to the model as JSON-like text; keep its keys stable.
    text = prompts.render("selection", **SAMPLES["selection"])
    line = next(line for line in text.splitlines() if line.startswith('{"articles"'))
    keys = re.findall(r'"(\w+)": string', line)
    assert keys == ["link", "title", "summary", "whyItMatters", "topic"]
    assert json.loads('{"ranking": [1, 2]}')  # the ranking answer format parses


def test_discovery_search_in_plain_language_or_keywords() -> None:
    sample = SAMPLES["discovery_search"]
    request = prompts.render("discovery_search", **sample)
    keywords = prompts.render("discovery_search", **{**sample, "conversational": False})
    bare = prompts.render("discovery_search", **{**sample, "keywords": [], "conversational": False})

    assert request.startswith("Currently active, high-quality blogs")
    assert "staying up to date on Postgres (pgvector, replication), plus" in request
    assert keywords == "Postgres pgvector replication blog\n"
    assert bare == "Postgres blog\n"


def test_a_directory_overrides_the_templates_it_holds(tmp_path: Path) -> None:
    (tmp_path / "web_search.md").write_text("Look up {{ query }} somewhere else.")
    sample = SAMPLES["web_search"]
    packaged = prompts.render("web_search", **sample)

    with prompts.overridden(tmp_path):
        changed = prompts.render("web_search", **sample)
        ranking = prompts.render("ranking", **SAMPLES["ranking"])

    assert changed == f"Look up {sample['query']} somewhere else.\n"
    assert ranking == prompts.render("ranking", **SAMPLES["ranking"])  # not in the directory
    assert prompts.render("web_search", **sample) == packaged  # restored afterwards


def test_an_override_named_like_no_template_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "rankng.md").write_text("typo")

    with pytest.raises(ValueError, match=r"no prompt is named like rankng\.md"):
        prompts.overridden(tmp_path).__enter__()
    with pytest.raises(ValueError, match="is not a directory"):
        prompts.overridden(tmp_path / "missing").__enter__()
