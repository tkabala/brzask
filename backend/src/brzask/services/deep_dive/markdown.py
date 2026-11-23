"""A finished deep dive as Markdown, for notes apps.

Everything that came from a model or a third party is escaped, and link
targets are percent-encoded, so no title or text can add structure or change
where a link points.
"""

import re
import unicodedata
from typing import Any
from urllib.parse import quote

from brzask.db.models import Article, DeepDive
from brzask.prompts import Language

HEADINGS: dict[str, dict[str, str]] = {
    "en": {
        "background": "Background",
        "practice": "In practice",
        "further": "Further reading",
        "sources": "Sources",
        "focus": "Focus",
        "nothing": "Nothing practical to try here.",
    },
    "pl": {
        "background": "Tło",
        "practice": "W praktyce",
        "further": "Co dalej czytać",
        "sources": "Źródła",
        "focus": "Ukierunkowanie",
        "nothing": "Nic tu nie da się wypróbować w praktyce.",
    },
}

SLUG_CHARS = 60
_SPECIAL = re.compile(r"([\\\[\]()`*_#<>])")
_SPACE = re.compile(r"\s+")
_BACKTICKS = re.compile(r"`+")
# Letters NFKD does not split into a base letter and a mark.
_ASCII = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ß": "ss", "đ": "d", "Đ": "D"})


def escape(text: str) -> str:
    """`text` on one line with every Markdown-significant character escaped."""
    return _SPECIAL.sub(r"\\\1", _SPACE.sub(" ", text).strip())


def link_target(url: str) -> str:
    """`url` with what could end or break a Markdown link target percent-encoded."""
    return quote(url.strip(), safe=":/?#[]@!$&'*+,;=%~-._")


def render(dive: DeepDive, article: Article, language: Language) -> str:
    """The dive as a Markdown document, headings in `language`."""
    words = HEADINGS.get(language.code, HEADINGS["en"])
    report: dict[str, Any] = dive.report or {"background": [], "practice": [], "further": []}
    sources = {int(s["n"]): s for s in dive.sources}
    finished = dive.finished_at or dive.created_at
    lines = [f"# {escape(article.digest_title or article.title)}", ""]
    lines.append(f"{finished:%Y-%m-%d} · {link_target(article.link)}")
    if dive.focus:
        lines.append(f"{words['focus']}: {escape(dive.focus)}")

    lines += ["", f"## {words['background']}", ""]
    for paragraph in report["background"]:
        lines += [_cited(paragraph["text"], paragraph["sources"]), ""]

    lines += [f"## {words['practice']}", ""]
    if not report["practice"]:
        lines += [words["nothing"], ""]
    for n, step in enumerate(report["practice"], start=1):
        lines += [f"{n}. {_cited(step['text'], step['sources'])}", ""]
        if step.get("command"):
            runs = _BACKTICKS.findall(step["command"])
            fence = "`" * max([3, *(len(run) + 1 for run in runs)])
            body = [f"   {line}".rstrip() for line in step["command"].splitlines()]
            lines += [f"   {fence}", *body, f"   {fence}", ""]

    if report["further"]:
        lines += [f"## {words['further']}", ""]
        for reading in report["further"]:
            source = sources.get(int(reading["source"]))
            if source is not None:
                lines.append(f"- {_link(source)}: {escape(reading['why'])}")
        lines.append("")

    lines += [f"## {words['sources']}", ""]
    lines += [f"{n}. {_link(sources[n])}" for n in sorted(sources)]
    return "\n".join(lines) + "\n"


def filename(dive: DeepDive, article: Article) -> str:
    """`<finished date>-<ascii slug of the title>.md`."""
    finished = dive.finished_at or dive.created_at
    title = (article.digest_title or article.title).translate(_ASCII)
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    slug = slug[:SLUG_CHARS].rstrip("-") or "deep-dive"
    return f"{finished:%Y-%m-%d}-{slug}.md"


def _cited(text: str, numbers: list[int]) -> str:
    marks = "".join(f"[{n}]" for n in numbers)
    return f"{escape(text)} {marks}" if marks else escape(text)


def _link(source: dict[str, Any]) -> str:
    return f"[{escape(source['title'])}]({link_target(source['url'])})"
