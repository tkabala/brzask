"""The committed OpenAPI document (`openapi.json` at the repository root).

Regenerate it with `just openapi`; a test fails while it differs from the app.
The frontend client is generated from this file.
"""

import json

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
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    print(render(), end="")
