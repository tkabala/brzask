"""Prompts, kept as Jinja templates next to this module (`<name>.md`).

Pipelines pass data (candidates, interests, opens) and the templates do the
wording, so a prompt can be changed, reviewed and compared with `replay`
without touching code. Undefined variables are errors, never empty text.
Templates whose name starts with `_` are shared blocks, included by others.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
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


# Templates found here replace the packaged ones (`overridden`).
_override: Path | None = None


@cache
def _environment(override: Path | None) -> jinja2.Environment:
    loader: jinja2.BaseLoader = jinja2.PackageLoader("brzask", "prompts")
    if override is not None:
        loader = jinja2.ChoiceLoader([jinja2.FileSystemLoader(override), loader])
    return jinja2.Environment(
        loader=loader,
        undefined=jinja2.StrictUndefined,
        autoescape=False,  # noqa: S701  (prompts are plain text, never HTML)
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )


def names() -> list[str]:
    """Every prompt that can be rendered (shared blocks excluded)."""
    return [name for name in _templates() if not name.startswith("_")]


def _templates() -> list[str]:
    """Every template, shared blocks included."""
    folder = files("brzask.prompts")
    return sorted(
        entry.name.removesuffix(".md") for entry in folder.iterdir() if entry.name.endswith(".md")
    )


def render(name: str, **context: Any) -> str:
    """The prompt `name` filled with `context`; raises on a missing variable."""
    return _environment(_override).get_template(f"{name}.md").render(**context).strip() + "\n"


@contextmanager
def overridden(directory: Path) -> Iterator[None]:
    """Render the templates in `directory` instead of the packaged ones of the same name.

    For trying changed prompts with `brzask replay`: the directory holds only
    the templates being changed. A file named like no template is an error,
    since a misspelt name would silently test the packaged prompt.
    """
    global _override
    if not directory.is_dir():
        raise ValueError(f"{directory} is not a directory")
    known = set(_templates())
    unknown = sorted(path.name for path in directory.glob("*.md") if path.stem not in known)
    if unknown:
        raise ValueError(f"no prompt is named like {', '.join(unknown)} in {directory}")
    previous, _override = _override, directory.resolve()
    try:
        yield
    finally:
        _override = previous
