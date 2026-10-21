"""The committed OpenAPI document (`openapi.json` at the repository root).

Regenerate it with `just openapi`; a test fails while it differs from the app.
The frontend client is generated from this file.
"""

import json
from typing import Any

from opentelemetry.metrics import NoOpMeterProvider
from pydantic import SecretStr
from sqlalchemy.orm import sessionmaker

from brzask.api.app import create_app
from brzask.api.metrics import prometheus_reader
from brzask.config.settings import AuthSettings


def render() -> str:
    _, registry = prometheus_reader()
    # The document needs no database, no metrics and no real secrets; it is the
    # same in every AUTH_MODE.
    placeholder = AuthSettings(
        mode="password",
        password_hash=SecretStr("$argon2id$placeholder"),
        session_secret=SecretStr("placeholder" * 4),
    )
    app = create_app(
        sessionmaker(),
        metrics_registry=registry,
        meter_provider=NoOpMeterProvider(),
        auth_settings=placeholder,
    )
    return json.dumps(in_javascript_order(app.openapi()), indent=2, ensure_ascii=False) + "\n"


def _array_index(key: str) -> int | None:
    """The key as a JavaScript array index ("200"), or None ("default", "007")."""
    return int(key) if key.isdigit() and str(int(key)) == key and int(key) < 2**32 - 1 else None


def in_javascript_order(value: Any) -> Any:
    """`value` with object keys in the order JavaScript keeps them: array-index
    keys first, ascending, then the others as they were.

    Release automation bumps `info.version` by parsing and rewriting the file in
    JavaScript, which would otherwise reorder response codes ("401", "403",
    "400" becomes "400", "401", "403") and leave the file differing from the app.
    """
    if isinstance(value, dict):
        indexed = sorted((k for k in value if _array_index(k) is not None), key=lambda k: int(k))
        named = [k for k in value if _array_index(k) is None]
        return {k: in_javascript_order(value[k]) for k in [*indexed, *named]}
    if isinstance(value, list):
        return [in_javascript_order(item) for item in value]
    return value


if __name__ == "__main__":
    print(render(), end="")
