"""Renders ``.env.example`` from the settings groups.

Run ``just env-example`` after changing a setting; a test fails while the
checked-in file is stale.
"""

import inspect

from pydantic import SecretStr
from pydantic_core import PydanticUndefined

from brzask.config.settings import GROUPS, SettingsGroup, env_name, is_secret

HEADER = """\
# brzask configuration.
#
# Copy to .env and adjust. Commented lines show the default value.
# Every secret can also be read from a file: set <NAME>_FILE=/path/to/file.
#
# Generated from backend/src/brzask/config/settings.py by `just env-example`.
"""


def format_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if isinstance(value, list | tuple):
        return ",".join(format_value(item) for item in value)
    return str(value)


def _render_group(group: type[SettingsGroup]) -> list[str]:
    doc = inspect.cleandoc(group.__doc__ or group.__name__)
    lines = [f"# {line}".rstrip() for line in doc.splitlines()]
    for name, field in group.model_fields.items():
        variable = env_name(group, name)
        description = field.description or ""
        if is_secret(field):
            description += f" Or {variable}_FILE."
        lines.append(f"# {description.strip()}")
        # Required values and secrets are left uncommented so they are easy to fill in.
        if field.default is PydanticUndefined or is_secret(field):
            example = field.examples[0] if field.examples else ""
            lines.append(f"{variable}={format_value(example)}")
        else:
            lines.append(f"# {variable}={format_value(field.default)}")
    return lines


def render() -> str:
    """The full ``.env.example`` contents."""
    sections = ["\n".join(_render_group(group)) for group in GROUPS]
    return HEADER + "\n" + "\n\n".join(sections) + "\n"


if __name__ == "__main__":
    print(render(), end="")
