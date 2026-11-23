from typing import Any

import pytest

from brzask import prompts
from brzask.db.models import Article
from brzask.services.deep_dive.gather import Source
from brzask.services.deep_dive.report import (
    Paragraph,
    Reading,
    Report,
    ReportError,
    Step,
    parse_report,
    write_report,
)
from tests.services.test_briefs import FakeLLM


def answer(**fields: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "background": [{"text": " Why it matters. ", "sources": [1, 2]}],
        "practice": [{"text": "Install it.", "command": "apt install x", "sources": [3]}],
        "further": [{"source": 2, "why": "The design notes."}],
    }
    value.update(fields)
    return value


def test_a_valid_answer_round_trips() -> None:
    report = parse_report(answer(), 4)

    assert report == Report(
        background=[Paragraph("Why it matters.", [1, 2])],
        practice=[Step("Install it.", "apt install x", [3])],
        further=[Reading(2, "The design notes.")],
    )
    assert Report.from_json(report.as_json()) == report


def test_unknown_source_numbers_are_removed() -> None:
    report = parse_report(answer(background=[{"text": "t", "sources": [2, 9, 2, 0, "3", True]}]), 4)
    assert report.background[0].sources == [2]


def test_a_paragraph_may_end_with_no_sources() -> None:
    report = parse_report(answer(background=[{"text": "t", "sources": [9]}]), 4)
    assert report.background == [Paragraph("t", [])]


def test_further_reading_cannot_be_the_article_or_unknown() -> None:
    further = [
        {"source": 1, "why": "itself"},
        {"source": 5, "why": "unknown"},
        {"source": 3, "why": " "},
        {"source": 2, "why": "kept"},
        {"source": 2, "why": "repeat"},
    ]
    assert parse_report(answer(further=further), 4).further == [Reading(2, "kept")]


def test_further_reading_is_cut_to_five() -> None:
    further = [{"source": n, "why": "w"} for n in range(2, 10)]
    assert len(parse_report(answer(further=further), 10).further) == 5


@pytest.mark.parametrize("background", [[], [{"text": "  ", "sources": [1]}], None, "text"])
def test_empty_background_is_an_error(background: Any) -> None:
    with pytest.raises(ReportError):
        parse_report(answer(background=background), 4)


def test_empty_practice_is_allowed() -> None:
    assert parse_report(answer(practice=[]), 4).practice == []
    assert parse_report(answer(practice=None), 4).practice == []


@pytest.mark.parametrize("command", ["  ", None, 7])
def test_blank_command_becomes_none(command: Any) -> None:
    practice = [{"text": "Do it.", "command": command, "sources": [1]}]
    assert parse_report(answer(practice=practice), 4).practice == [Step("Do it.", None, [1])]


@pytest.mark.parametrize("value", [None, "text", [1, 2]])
def test_non_object_answer_is_an_error(value: Any) -> None:
    with pytest.raises(ReportError):
        parse_report(value, 4)


SOURCES = [
    Source(1, "https://a.example/", "The article", "article", 1, "Article text."),
    Source(2, "https://b.example/", "Docs", "web", None, "Docs text."),
]


def write(llm: FakeLLM) -> Report:
    article = Article(id=1, title="The article", link="https://a.example/")
    return write_report(llm, article, SOURCES, [], "for Proxmox", prompts.language("en"), None)


def test_an_invalid_answer_is_asked_again() -> None:
    llm = FakeLLM(lambda _prompt, n: {} if n == 1 else answer(further=[]))

    report = write(llm)

    assert report.background[0].text == "Why it matters."
    assert llm.purposes == ["deep_dive_report", "deep_dive_report"]


def test_two_invalid_answers_fail() -> None:
    llm = FakeLLM(lambda _prompt, _n: {"background": []})
    with pytest.raises(ReportError):
        write(llm)
    assert len(llm.prompts) == 2
