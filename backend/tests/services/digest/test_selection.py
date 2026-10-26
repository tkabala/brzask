from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from brzask import prompts
from brzask.clients.llm import Completion
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.services.digest.pool import Candidate
from brzask.services.digest.selection import (
    DIGEST_SIZE,
    PROMPT_TEXT_CHARS,
    SelectionError,
    parse_selection,
    select_digest,
    selection_prompt,
)
from tests.factories import Factories
from tests.services.digest.fakes import NOW, context

ENGLISH = prompts.language("en")
POLISH = prompts.language("pl")


def candidate(n: int, **fields: Any) -> Candidate:
    defaults: dict[str, Any] = {
        "link": f"https://news.example/{n}",
        "snippet": None,
        "published_at": NOW,
        "rank": n,
        "release": False,
    }
    return Candidate(
        title=f"Article {n}", source_id=n, source_name=f"Source {n}", **(defaults | fields)
    )


def item(n: int, topic: str = "Rust", **fields: Any) -> dict[str, Any]:
    return {
        "link": f"https://news.example/{n}",
        "title": f"Title {n}",
        "summary": f"Summary {n}",
        "whyItMatters": f"Why {n}",
        "topic": topic,
    } | fields


CANDIDATES = [candidate(n) for n in range(1, 11)]


def test_another_digest_size_can_be_tried() -> None:
    answer = {"articles": [item(n) for n in range(1, 10)]}

    assert len(parse_selection(answer, CANDIDATES, ENGLISH, size=3)) == 3
    assert "select exactly 3 articles" in selection_prompt(CANDIDATES, [], ENGLISH, size=3)


def test_picks_are_grouped_by_topic_in_order_of_appearance() -> None:
    answer = {"articles": [item(3, "Rust"), item(1, "Postgres"), item(5, "Rust")]}

    picks = parse_selection(answer, CANDIDATES, ENGLISH)

    assert [(p.candidate.link, p.position, p.topic) for p in picks] == [
        ("https://news.example/3", 1, "Rust"),
        ("https://news.example/5", 2, "Rust"),
        ("https://news.example/1", 3, "Postgres"),
    ]
    assert (picks[0].title, picks[0].summary, picks[0].why_it_matters) == (
        "Title 3",
        "Summary 3",
        "Why 3",
    )


def test_unknown_and_repeated_links_are_skipped() -> None:
    answer = {
        "articles": [
            item(1),
            item(99),  # invented
            item(1, title="Again"),
            {"link": "https://news.example/2/", "title": "Slash"},  # a trailing slash added
            "not an object",
            {"title": "No link"},
        ]
    }

    picks = parse_selection(answer, CANDIDATES, ENGLISH)

    assert [p.candidate.link for p in picks] == ["https://news.example/1", "https://news.example/2"]
    assert picks[0].title == "Title 1"


def test_a_link_with_its_query_dropped_still_matches_one_candidate() -> None:
    tracked = "https://www.infoq.com/news/argon/?utm_campaign=infoq_content&utm_source=infoq"
    candidates = [candidate(1, link=tracked), candidate(2)]
    answer = {"articles": [item(1, link="https://www.infoq.com/news/argon/")]}

    assert [p.candidate.link for p in parse_selection(answer, candidates, ENGLISH)] == [tracked]


def test_a_link_without_its_query_matching_two_candidates_is_skipped() -> None:
    candidates = [
        candidate(1, link="https://forum.example/view?t=1"),
        candidate(2, link="https://forum.example/view?t=2"),
    ]
    answer = {"articles": [item(1, link="https://forum.example/view")]}

    assert parse_selection(answer, candidates, ENGLISH) == []


def test_a_link_with_another_query_is_not_the_one_candidate_on_its_path() -> None:
    candidates = [candidate(1, link="https://www.youtube.com/watch?v=AAA")]
    answer = {"articles": [item(1, link="https://www.youtube.com/watch?v=BBB")]}

    assert parse_selection(answer, candidates, ENGLISH) == []


def test_a_link_urlsplit_rejects_is_skipped() -> None:
    answer = {"articles": [item(1, link="https://[article-url]/x"), item(2)]}

    picks = parse_selection(answer, CANDIDATES, ENGLISH)

    assert [p.candidate.link for p in picks] == ["https://news.example/2"]


def test_at_most_digest_size_picks() -> None:
    answer = {"articles": [item(n) for n in range(1, 11)]}

    assert len(parse_selection(answer, CANDIDATES, ENGLISH)) == DIGEST_SIZE


def test_missing_fields_fall_back() -> None:
    answer = {"articles": [{"link": "https://news.example/4", "topic": " ", "summary": 5}]}

    (pick,) = parse_selection(answer, CANDIDATES, POLISH)

    assert (pick.title, pick.summary, pick.why_it_matters, pick.topic) == (
        "Article 4",
        "",
        "",
        "Ogólne",
    )


@pytest.mark.parametrize("answer", [None, [], {"articles": "x"}, {"picks": [item(1)]}])
def test_answers_of_another_shape_pick_nothing(answer: Any) -> None:
    assert parse_selection(answer, CANDIDATES, ENGLISH) == []


def test_prompt_shows_the_text_cut_to_length_or_the_snippet() -> None:
    candidates = [
        candidate(1, text="x" * 5000),
        candidate(2, snippet="Only a snippet", published_at=None),
    ]

    text = selection_prompt(candidates, [], POLISH)

    assert "1. [Article 1](https://news.example/1)" in text
    assert "x" * PROMPT_TEXT_CHARS + "\n" in text
    assert "x" * (PROMPT_TEXT_CHARS + 1) not in text
    assert "Published: 2026-10-18" in text
    assert "   Only a snippet" in text
    assert "Published: unknown" in text
    assert "in Polish" in text


def test_prompt_marks_release_notes() -> None:
    text = selection_prompt([candidate(1, release=True), candidate(2)], [], ENGLISH)

    assert text.count("Release notes: yes") == 1
    assert text.index("Release notes: yes") < text.index("2. [Article 2]")


class FakeModel:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def complete_json(
        self, prompt: str, *, purpose: str, meter: UsageMeter | None = None
    ) -> tuple[Any, Completion]:
        self.prompts.append(prompt)
        return self.answer, Completion("{}", CallUsage("test/model", purpose, 1, 1, None, 1))


def test_select_digest_uses_the_active_interests_and_records_stats(
    sessions: sessionmaker[Session], make: Factories
) -> None:
    make.interest("Rust", notes="want: compiler internals")
    make.interest("Knitting", active=False)
    model = FakeModel({"articles": [item(2, "Rust"), item(1, "General")]})
    run = context(sessions)

    picks = select_digest(run, CANDIDATES, model, ENGLISH)

    assert [p.position for p in picks] == [1, 2]
    assert "[reader note: want: compiler internals]" in model.prompts[0]
    assert "Knitting" not in model.prompts[0]
    assert run.stats["selection"] == {
        "prompt_chars": len(model.prompts[0]),
        "candidates": 10,
        "picked": 2,
        "topics": ["Rust", "General"],
    }
    assert "selection" in run.timings


def test_an_answer_naming_no_candidate_fails(sessions: sessionmaker[Session]) -> None:
    model = FakeModel({"articles": [item(99)]})

    with pytest.raises(SelectionError):
        select_digest(context(sessions), CANDIDATES, model, ENGLISH)
