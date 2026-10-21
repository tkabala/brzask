"""Renders ``docs/configuration.md``, the settings reference of the docs site.

Generated from the same settings groups as ``.env.example`` by
``just env-example``; a test fails while the checked-in page is stale.
"""

import inspect

from pydantic_core import PydanticUndefined

from brzask.config.env_example import format_value
from brzask.config.settings import GROUPS, SettingsGroup, env_name, is_secret

HEADER = """\
# Configuration

<!-- Generated from backend/src/brzask/config/settings.py by `just env-example`. -->

brzask is configured with environment variables. With Docker Compose they go
in a `.env` file next to `compose.yaml`; [`.env.example`](https://github.com/tkabala/brzask/blob/main/.env.example)
lists all of them with their defaults, ready to copy.

Every secret can also be read from a file: set `<NAME>_FILE` to its path
instead of setting `<NAME>`. The compose file does this for the secrets
`brzask setup` writes to `./secrets`. Set a secret one way, not both.

Which models and endpoints to use is described in [Providers](providers.md).
"""


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _default(group: type[SettingsGroup], name: str) -> str:
    field = group.model_fields[name]
    if field.default is PydanticUndefined:
        return "required"
    if is_secret(field):
        return "secret" if field.default is None else "secret, set"
    value = format_value(field.default)
    return f"`{value}`" if value else "(none)"


def _render_group(group: type[SettingsGroup]) -> str:
    doc = " ".join(inspect.cleandoc(group.__doc__ or group.__name__).split()).rstrip(".")
    # "Database: Postgres 17 with ..." becomes the heading "Database" and a line under it;
    # so does a first sentence or clause ending in ". " or "; ".
    cut = min((doc.find(mark) for mark in (": ", ". ", "; ") if mark in doc), default=len(doc))
    title, rest = doc[:cut], doc[cut + 2 :]
    lines = [f"## {title}", ""]
    if rest:
        lines += [rest[0].upper() + rest[1:] + ".", ""]
    lines += ["| Variable | Default | Description |", "|---|---|---|"]
    for name, field in group.model_fields.items():
        description = field.description or ""
        lines.append(
            f"| `{env_name(group, name)}` | {_default(group, name)} | {_cell(description)} |"
        )
    return "\n".join(lines)


def render() -> str:
    """The full ``docs/configuration.md`` contents."""
    return HEADER + "\n" + "\n\n".join(_render_group(group) for group in GROUPS) + "\n"


if __name__ == "__main__":
    print(render(), end="")
