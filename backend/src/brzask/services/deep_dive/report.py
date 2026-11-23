"""The write stage: the report, cleaned to its shape and to the gathered sources.

The model names sources by number only. Numbers outside the list are removed,
so every link a report shows comes from the gathered sources (ADR 0023).
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from brzask import prompts
from brzask.clients.llm import InvalidJSONError
from brzask.clients.usage import UsageMeter
from brzask.db.models import Article
from brzask.log import get_logger
from brzask.prompts import Language
from brzask.services.deep_dive.gather import Source
from brzask.services.digest.ranking import ChatModel

log = get_logger(__name__)

MAX_FURTHER = 5


class ReportError(Exception):
    """The model's answer cannot be cleaned into a report."""


@dataclass(frozen=True, slots=True)
class Paragraph:
    text: str
    sources: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Step:
    text: str
    command: str | None = None
    sources: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Reading:
    source: int
    why: str


@dataclass(frozen=True, slots=True)
class Report:
    background: list[Paragraph]
    practice: list[Step]
    further: list[Reading]

    def as_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "Report":
        return cls(
            background=[Paragraph(p["text"], list(p["sources"])) for p in value["background"]],
            practice=[
                Step(s["text"], s.get("command"), list(s["sources"])) for s in value["practice"]
            ],
            further=[Reading(r["source"], r["why"]) for r in value["further"]],
        )


def parse_report(answer: Any, source_count: int) -> Report:
    """The model's answer cleaned to a report citing sources 1..`source_count`.

    Blank paragraphs and steps are dropped, unknown source numbers removed, a
    blank command becomes None; further reading keeps known sources other than
    the article (1), once each, at most `MAX_FURTHER`. Raises `ReportError`
    when the answer is not an object or no background paragraph is left.
    """
    if not isinstance(answer, dict):
        raise ReportError(f"expected a JSON object, got {type(answer).__name__}")
    background = [
        Paragraph(text, _numbers(item.get("sources"), source_count))
        for item in _items(answer.get("background"))
        if (text := _text(item.get("text")))
    ]
    if not background:
        raise ReportError("the report has no background paragraph")
    practice = [
        Step(text, _text(item.get("command")) or None, _numbers(item.get("sources"), source_count))
        for item in _items(answer.get("practice"))
        if (text := _text(item.get("text")))
    ]
    further: list[Reading] = []
    for item in _items(answer.get("further")):
        source, why = item.get("source"), _text(item.get("why"))
        if not isinstance(source, int) or isinstance(source, bool):
            continue
        if not 2 <= source <= source_count or not why:
            continue
        if any(reading.source == source for reading in further):
            continue
        further.append(Reading(source, why))
    return Report(background, practice, further[:MAX_FURTHER])


def write_report(
    llm: ChatModel,
    article: Article,
    sources: Sequence[Source],
    interests: Sequence[dict[str, Any]],
    focus: str,
    language: Language,
    meter: UsageMeter | None,
) -> Report:
    """The report on `article` from `sources`; asked once more when the answer is unusable.

    Raises `ReportError` when the second answer is unusable too, and lets
    other errors of the call through.
    """
    prompt = prompts.render(
        "deep_dive_report",
        interests=interests,
        title=article.title,
        focus=focus,
        language=language,
        sources=[
            {"n": s.n, "title": s.title, "url": s.url, "origin": s.origin, "text": s.text}
            for s in sources
        ],
    )
    for attempt in (1, 2):
        try:
            answer, _ = llm.complete_json(prompt, purpose="deep_dive_report", meter=meter)
            return parse_report(answer, len(sources))
        except (ReportError, InvalidJSONError) as error:
            if attempt == 2:
                raise ReportError(str(error)) from error
            log.info("deep dive report unusable; asking again", error=str(error))
    raise AssertionError("unreachable")  # pragma: no cover


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_number(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _numbers(value: Any, source_count: int) -> list[int]:
    numbers: list[int] = []
    for item in value if isinstance(value, list) else []:
        if _is_number(item) and 1 <= item <= source_count and item not in numbers:
            numbers.append(item)
    return numbers
