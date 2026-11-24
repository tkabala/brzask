"""An answer, cleaned to its shape and to the conversation's sources.

The model names sources by number only. Numbers the conversation does not
have are removed, so every link an answer shows is one of its sources.
"""

import re
from collections.abc import Collection
from dataclasses import asdict, dataclass, field
from typing import Any

# Real check (2026-11-24, 24 answers and 4 search rounds on 3 articles): suggestions were 26-73
# characters once asked for under 100; one over 120 lost its end when cut, so
# longer ones are dropped.
SUGGESTIONS = 3  # follow-up questions kept
SUGGESTION_CHARS = 120  # a suggestion is a tap-to-ask button


class AnswerError(Exception):
    """The model's answer cannot be cleaned into an answer."""


@dataclass(frozen=True, slots=True)
class Paragraph:
    text: str
    sources: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Answer:
    paragraphs: list[Paragraph]
    enough: bool
    suggestions: list[str]

    def as_json(self) -> dict[str, Any]:
        """As stored: `{answer: [{text, sources}], enough, suggestions}`."""
        return {
            "answer": [asdict(paragraph) for paragraph in self.paragraphs],
            "enough": self.enough,
            "suggestions": list(self.suggestions),
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "Answer":
        return cls(
            [Paragraph(p["text"], list(p["sources"])) for p in value["answer"]],
            bool(value["enough"]),
            list(value["suggestions"]),
        )

    @property
    def text(self) -> str:
        """The paragraphs without their numbers, for the history of later questions."""
        return "\n\n".join(paragraph.text for paragraph in self.paragraphs)


def parse_answer(value: Any, numbers: Collection[int], question: str) -> Answer:
    """The model's answer cleaned to one citing only `numbers`.

    Blank paragraphs are dropped, numbers written into the text ("[1]")
    removed and unknown or repeated numbers dropped;
    `enough` is False only for a JSON false; suggestions are stripped, those over
    `SUGGESTION_CHARS` dropped, as are repeats and the question itself dropped (case
    ignored), at most `SUGGESTIONS`. Raises `AnswerError` when the value is
    not an object or no paragraph is left.
    """
    if not isinstance(value, dict):
        raise AnswerError(f"expected a JSON object, got {type(value).__name__}")
    paragraphs = [
        Paragraph(text, _numbers(item.get("sources"), numbers))
        for item in _items(value.get("answer"))
        if (text := _prose(item.get("text")))
    ]
    if not paragraphs:
        raise AnswerError("the answer has no paragraph")
    return Answer(paragraphs, value.get("enough") is not False, _suggestions(value, question))


def _suggestions(value: dict[str, Any], question: str) -> list[str]:
    seen = {question.strip().casefold()}
    kept: list[str] = []
    raw = value.get("suggestions")
    for item in raw if isinstance(raw, list) else []:
        text = _text(item).strip()
        # Dropped, not cut: a cut question loses its end (and its question mark).
        if not text or len(text) > SUGGESTION_CHARS or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        kept.append(text)
    return kept[:SUGGESTIONS]


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


# "[1]", "[2, 3]" or "[2][3]" written into the text: the page shows the numbers
# as buttons already (3 of 13 answers in the real check carried them).
_INLINE_NUMBERS = re.compile(r"\s*\[\d+(?:\s*,\s*\d+)*\]")


def _prose(value: Any) -> str:
    """A paragraph's text without source numbers written into it."""
    return _INLINE_NUMBERS.sub("", _text(value)).strip()


def _numbers(value: Any, known: Collection[int]) -> list[int]:
    kept: list[int] = []
    for item in value if isinstance(value, list) else []:
        is_number = isinstance(item, int) and not isinstance(item, bool)
        if is_number and item in known and item not in kept:
            kept.append(item)
    return kept
