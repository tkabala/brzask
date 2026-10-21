"""The API against its own OpenAPI document, with requests Schemathesis generates."""

from pathlib import Path
from typing import Any

import pytest
import schemathesis
from fastapi import FastAPI
from schemathesis.config import SchemathesisConfig
from schemathesis.specs.openapi.schemas import OpenApiSchema

from brzask.api.app import OPENAPI_URL
from brzask.api.openapi import render

CONFIG = """
[[operations]]
include-path-regex = "^/api/v1/"
# A cursor is any string to the schema; only the ones the API handed out are valid.
checks.positive_data_acceptance.expected-statuses = ["2xx", "400"]
"""


@pytest.fixture
def api_schema(app: FastAPI) -> OpenApiSchema:
    return schemathesis.openapi.from_asgi(
        OPENAPI_URL, app, config=SchemathesisConfig.from_str(CONFIG)
    )


schema = schemathesis.pytest.from_fixture("api_schema")


@schema.parametrize()
def test_api_conforms_to_its_schema(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate()


def test_committed_openapi_is_up_to_date() -> None:
    path = Path(__file__).parents[3] / "openapi.json"

    assert path.read_text() == render(), "stale openapi.json: run `just openapi`"
