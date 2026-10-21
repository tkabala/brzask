"""The API against its own OpenAPI document, with requests Schemathesis generates."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import schemathesis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from schemathesis.config import SchemathesisConfig
from schemathesis.specs.openapi.schemas import OpenApiSchema

from brzask.api.app import OPENAPI_URL
from brzask.api.openapi import in_javascript_order, render
from brzask.config.settings import AuthSettings
from tests.api.conftest import PASSWORD

# The first entry matching an operation applies.
CONFIG = """
[[operations]]
include-path = "/api/v1/auth/login"
# A generated password is wrong, and enough of them lock the client out.
checks.positive_data_acceptance.expected-statuses = ["2xx", "401", "429"]

[[operations]]
include-path-regex = "^/api/v1/"
# Beside the defaults (2xx, 404 for an unknown ID, 409 for a duplicate): 400, as
# a cursor is any string to the schema but only the ones the API handed out are
# valid, and services reject values a schema cannot describe (a blank topic).
checks.positive_data_acceptance.expected-statuses = ["2xx", "400", "404", "409"]
"""


@pytest.fixture
def auth_settings(password_auth: AuthSettings) -> AuthSettings:
    """As deployed: Schemathesis also checks that requests without a session fail."""
    return password_auth


# The session of the running test, for the auth provider below.
_session: dict[str, str] = {}


@pytest.fixture
def logged_in(app: FastAPI) -> Iterator[None]:
    """Log in on the test's app; Schemathesis sends the session as auth."""
    client = TestClient(app, base_url="https://testserver")
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    _session.update(token=client.cookies["brzask_session"], csrf=response.json()["csrf_token"])
    yield
    _session.clear()


# Not cached: each test logs in on its own database, and reading it is cheap.
@schemathesis.auth(refresh_interval=None)
class SessionAuth:
    """Knowing the auth, Schemathesis also checks that requests without it fail."""

    def get(
        self, case: schemathesis.Case[Any], context: schemathesis.AuthContext
    ) -> dict[str, str]:
        return dict(_session)

    def set(
        self,
        case: schemathesis.Case[Any],
        data: dict[str, str],
        context: schemathesis.AuthContext,
    ) -> None:
        case.cookies["brzask_session"] = data["token"]
        case.headers["X-CSRF-Token"] = data["csrf"]


@pytest.fixture
def api_schema(app: FastAPI) -> OpenApiSchema:
    return schemathesis.openapi.from_asgi(
        OPENAPI_URL, app, config=SchemathesisConfig.from_str(CONFIG)
    )


# Logging out would end the session the other requests use.
schema = schemathesis.pytest.from_fixture("api_schema").exclude(path="/api/v1/auth/logout")


@schema.parametrize()
@pytest.mark.usefixtures("logged_in")
def test_api_conforms_to_its_schema(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate()


def test_committed_openapi_is_up_to_date() -> None:
    path = Path(__file__).parents[3] / "openapi.json"

    assert path.read_text() == render(), "stale openapi.json: run `just openapi`"


def test_document_keys_are_in_javascript_order() -> None:
    document = {"b": 1, "403": 2, "a": {"default": 3, "401": 4, "200": 5}, "007": 6}

    ordered = in_javascript_order(document)

    assert list(ordered) == ["403", "b", "a", "007"]
    assert list(ordered["a"]) == ["200", "401", "default"]
