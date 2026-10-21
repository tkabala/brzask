from http import HTTPStatus

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brzask.api import problems
from brzask.api.problems import ProblemError
from brzask.services.errors import ConflictError, NotFoundError, ServiceError

TYPE = "application/problem+json"


def app_raising(error: Exception) -> TestClient:
    app = FastAPI()
    problems.install(app)

    @app.get("/boom")
    def boom() -> None:
        raise error

    @app.get("/limit")
    def limit(value: int) -> int:
        return value

    return TestClient(app, raise_server_exceptions=False)


def test_unknown_route_is_a_problem(client: TestClient) -> None:
    response = client.get("/api/v1/nothing-here")

    assert response.status_code == 404
    assert response.headers["content-type"] == TYPE
    assert response.json() == {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "instance": "/api/v1/nothing-here",
    }


def test_wrong_method_lists_every_method_of_the_path(client: TestClient) -> None:
    response = client.post("/api/v1/pause")

    assert response.status_code == 405
    assert response.headers["content-type"] == TYPE
    # One route per method: Starlette alone would name only the first (GET).
    assert response.headers.get_list("allow") == ["DELETE, GET, PUT"]
    assert client.post("/healthz").headers["allow"] == "GET"
    # Not in the document: Starlette's own header stays.
    assert client.post("/metrics").headers["allow"] == "GET"


def test_validation_errors_list_each_field() -> None:
    response = app_raising(ValueError()).get("/limit", params={"value": "many"})

    assert response.status_code == 422
    assert response.headers["content-type"] == TYPE
    body = response.json()
    assert body["title"] == "Unprocessable Content"
    assert body["errors"] == [
        {
            "location": ["query", "value"],
            "message": "Input should be a valid integer, unable to parse string as an integer",
            "type": "int_parsing",
        }
    ]


def test_service_errors_map_to_statuses() -> None:
    cases = [
        (NotFoundError("no source 7"), 404),
        (ConflictError("source exists"), 409),
        (ServiceError("bad URL"), 400),
    ]
    for error, status in cases:
        response = app_raising(error).get("/boom")
        assert response.status_code == status
        assert response.json()["detail"] == str(error)


def test_problem_error_carries_its_detail() -> None:
    response = app_raising(ProblemError(HTTPStatus.SERVICE_UNAVAILABLE, "later")).get("/boom")

    assert response.status_code == 503
    assert response.json()["detail"] == "later"


def test_unexpected_error_hides_the_cause() -> None:
    response = app_raising(RuntimeError("password=hunter2")).get("/boom")

    assert response.status_code == 500
    assert response.headers["content-type"] == TYPE
    assert "hunter2" not in response.text
    assert response.json()["title"] == "Internal Server Error"
