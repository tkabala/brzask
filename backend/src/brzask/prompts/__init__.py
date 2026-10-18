"""Prompts, kept as Jinja templates next to this module (`<name>.md`).

Pipelines pass data (candidates, interests, opens) and the templates do the
wording, so a prompt can be changed, reviewed and compared with `replay`
without touching code. Undefined variables are errors, never empty text.
Templates whose name starts with `_` are shared blocks, included by others.
"""

from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any, Literal

import jinja2


@dataclass(frozen=True, slots=True)
class Language:
    """The digest language, as prompts refer to it."""

    code: str
    name: str  # in English, for the instruction "write in ..."
    fallback_topic: str  # topic for articles that match no interest, in the language itself


LANGUAGES: dict[str, Language] = {
    "en": Language("en", "English", "General"),
    "pl": Language("pl", "Polish", "Ogólne"),
}


def language(code: Literal["en", "pl"] | str) -> Language:
    try:
        return LANGUAGES[code]
    except KeyError:
        raise ValueError(f"unsupported digest language {code!r}") from None


@cache
def _environment() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.PackageLoader("brzask", "prompts"),
        undefined=jinja2.StrictUndefined,
        autoescape=False,  # noqa: S701  (prompts are plain text, never HTML)
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )


def names() -> list[str]:
    """Every prompt that can be rendered (shared blocks excluded)."""
    folder = files("brzask.prompts")
    return sorted(
        entry.name.removesuffix(".md")
        for entry in folder.iterdir()
        if entry.name.endswith(".md") and not entry.name.startswith("_")
    )


def render(name: str, **context: Any) -> str:
    """The prompt `name` filled with `context`; raises on a missing variable."""
    return _environment().get_template(f"{name}.md").render(**context).strip() + "\n"
