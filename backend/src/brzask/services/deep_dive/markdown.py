"""A finished deep dive as Markdown, for notes apps.

Everything that came from a model or a third party is escaped, and link
targets are percent-encoded, so no title or text can add structure or change
where a link points.
"""

import re
import unicodedata
from datetime import UTC, tzinfo
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

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
# Parentheses stay: with brackets escaped they cannot form a link.
_SPECIAL = re.compile(r"([\\\[\]`*_#<>])")
_CODE = re.compile(r"(`[^`\n]+`)")
_SPACE = re.compile(r"\s+")
# What notes apps turn into a link or a block without any Markdown syntax:
# bare URLs and `www.` names (GFM autolinks), and a list item, thematic break
# or setext underline at the start of a line. A backslash before the colon,
# dot or marker keeps them text.
_AUTOLINK = re.compile(r"(?i)(\b(?:https?|ftp)):(?=//)|(\bwww)\.")
_BLOCK_START = re.compile(r"^(\d*)([-+=.)])")
_BACKTICKS = re.compile(r"`+")
# Letters NFKD does not split into a base letter and a mark.
_ASCII = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ß": "ss", "đ": "d", "Đ": "D"})


def escape(text: str) -> str:
    """`text` on one line with every Markdown-significant character escaped,
    except inside inline code spans (`like this`), which stay code. Bare URLs
    stay text, not links."""
    parts = _CODE.split(_SPACE.sub(" ", text).strip())
    escaped = "".join(
        part if n % 2 else _AUTOLINK.sub(_unlink, _SPECIAL.sub(r"\\\1", part))
        for n, part in enumerate(parts)
    )
    return _BLOCK_START.sub(_unblock, escaped, count=1)


def _unlink(match: re.Match[str]) -> str:
    scheme, www = match.groups()
    return f"{scheme}\\:" if scheme else f"{www}\\."


def _unblock(match: re.Match[str]) -> str:
    digits, marker = match.groups()
    # Only "-", "+" and "=" start a block alone; "." and ")" after digits.
    if bool(digits) != (marker in ".)"):
        return match.group(0)
    return f"{digits}\\{marker}"


def without_tracking(url: str) -> str:
    """`url` without `utm_*` query parameters."""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.startswith("utm_")
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


def link_target(url: str) -> str:
    """`url` with what could end or break a Markdown link target percent-encoded."""
    return quote(url.strip(), safe=":/?#[]@!$&'*+,;=%~-._")


def render(dive: DeepDive, article: Article, language: Language, tz: tzinfo = UTC) -> str:
    """The dive as a Markdown document, headings in `language`, dated in `tz`."""
    words = HEADINGS.get(language.code, HEADINGS["en"])
    report: dict[str, Any] = dive.report or {"background": [], "practice": [], "further": []}
    sources = {int(s["n"]): s for s in dive.sources}
    finished = (dive.finished_at or dive.created_at).astimezone(tz)
    lines = [f"# {escape(article.digest_title or article.title)}", ""]
    lines.append(f"{finished:%Y-%m-%d} · {link_target(without_tracking(article.link))}")
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


def filename(dive: DeepDive, article: Article, tz: tzinfo = UTC) -> str:
    """`<finished date in tz>-<ascii slug of the title>.md`."""
    finished = (dive.finished_at or dive.created_at).astimezone(tz)
    return f"{finished:%Y-%m-%d}-{slug(article.digest_title or article.title, 'deep-dive')}.md"


def slug(title: str, fallback: str) -> str:
    """`title` as lowercase ASCII words joined by hyphens, at most `SLUG_CHARS` long."""
    ascii_title = unicodedata.normalize("NFKD", title.translate(_ASCII))
    words = re.sub(r"[^a-z0-9]+", "-", ascii_title.encode("ascii", "ignore").decode().lower())
    return words.strip("-")[:SLUG_CHARS].rstrip("-") or fallback


def _cited(text: str, numbers: list[int]) -> str:
    marks = "".join(f"[{n}]" for n in numbers)
    return f"{escape(text)} {marks}" if marks else escape(text)


def _link(source: dict[str, Any]) -> str:
    return f"[{escape(source['title'])}]({link_target(source['url'])})"
