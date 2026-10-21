"""The committed OpenAPI document (`openapi.json` at the repository root).

Regenerate it with `just openapi`; a test fails while it differs from the app.
The frontend client is generated from this file.
"""

import json

from opentelemetry.metrics import NoOpMeterProvider
from sqlalchemy.orm import sessionmaker

from brzask.api.app import create_app
from brzask.api.metrics import prometheus_reader


def render() -> str:
    _, registry = prometheus_reader()
    # The document needs no database and no metrics.
    app = create_app(sessionmaker(), metrics_registry=registry, meter_provider=NoOpMeterProvider())
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    print(render(), end="")
