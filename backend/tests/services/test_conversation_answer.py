from typing import Any

import pytest

from brzask.services.conversation.answer import (
    SUGGESTION_CHARS,
    Answer,
    AnswerError,
    Paragraph,
    parse_answer,
)

NUMBERS = {1, 2, 3}


def test_a_valid_answer() -> None:
    answer = parse_answer(
        {
            "answer": [{"text": " It reads ahead. ", "sources": [1, 3]}],
            "enough": True,
            "suggestions": ["How do I turn it on?"],
        },
        NUMBERS,
        "What changed?",
    )
    assert answer == Answer([Paragraph("It reads ahead.", [1, 3])], True, ["How do I turn it on?"])
    assert answer.as_json() == {
        "answer": [{"text": "It reads ahead.", "sources": [1, 3]}],
        "enough": True,
        "suggestions": ["How do I turn it on?"],
    }
    assert Answer.from_json(answer.as_json()) == answer


def test_unknown_numbers_and_repeats_are_removed() -> None:
    answer = parse_answer(
        {"answer": [{"text": "A.", "sources": [1, 9, 1, "2", True, 0, 3]}]}, NUMBERS, "Q?"
    )
    assert answer.paragraphs == [Paragraph("A.", [1, 3])]


def test_numbers_need_not_be_consecutive() -> None:
    answer = parse_answer({"answer": [{"text": "A.", "sources": [5, 2]}]}, {1, 5}, "Q?")
    assert answer.paragraphs[0].sources == [5]


def test_blank_paragraphs_are_dropped() -> None:
    answer = parse_answer(
        {"answer": [{"text": "  "}, "loose", {"text": "Kept."}, {"sources": [1]}]}, NUMBERS, "Q?"
    )
    assert answer.paragraphs == [Paragraph("Kept.", [])]


@pytest.mark.parametrize(
    "value", [{}, {"answer": []}, {"answer": [{"text": " "}]}, {"answer": "text"}, [], "text", None]
)
def test_no_paragraph_is_an_error(value: Any) -> None:
    with pytest.raises(AnswerError):
        parse_answer(value, NUMBERS, "Q?")


@pytest.mark.parametrize(
    ("enough", "expected"), [(None, True), ("false", True), (0, True), (False, False), (True, True)]
)
def test_enough_is_false_only_for_a_json_false(enough: Any, expected: bool) -> None:
    value: dict[str, Any] = {"answer": [{"text": "A."}]}
    if enough is not None:
        value["enough"] = enough
    assert parse_answer(value, NUMBERS, "Q?").enough is expected


def test_suggestions_are_cleaned() -> None:
    value = {
        "answer": [{"text": "A."}],
        "suggestions": [
            " Is it faster? ",
            "is it FASTER?",
            "What changed?",
            "",
            42,
            "x" * 500,
            "Where are the docs?",
            "One too many?",
        ],
    }
    answer = parse_answer(value, NUMBERS, "  what changed? ")
    assert answer.suggestions == ["Is it faster?", "x" * SUGGESTION_CHARS, "Where are the docs?"]


def test_ten_suggestions_become_three() -> None:
    value = {"answer": [{"text": "A."}], "suggestions": [f"Question {n}?" for n in range(10)]}
    assert len(parse_answer(value, NUMBERS, "Q?").suggestions) == 3


def test_suggestions_that_are_not_a_list_are_none() -> None:
    value = {"answer": [{"text": "A."}], "suggestions": "Why?"}
    assert parse_answer(value, NUMBERS, "Q?").suggestions == []
