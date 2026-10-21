"""Errors as RFC 9457 problem details.

Every error response, from a missing route to a failed validation, has the
media type `application/problem+json` and the same shape: `type`, `title`,
`status` and, when there is more to say, `detail`. Validation errors also list
`errors`, one per invalid field. Clients show `detail` (or `title`) as it is.
"""

import re
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from brzask.clients.retry import APIError
from brzask.log import get_logger
from brzask.services.errors import ConflictError, NotFoundError, ServiceError

log = get_logger(__name__)

MEDIA_TYPE = "application/problem+json"


class FieldError(BaseModel):
    location: list[str | int] = Field(
        description='Where the invalid value is, e.g. ["query", "limit"].'
    )
    message: str
    type: str = Field(description='Machine-readable kind of error, e.g. "less_than_equal".')


class Problem(BaseModel):
    type: str = Field(
        "about:blank",
        description="URI of the problem type; about:blank means the status says it all.",
    )
    title: str = Field(description="Short summary of the problem type.")
    status: int = Field(ge=400, le=599)
    detail: str | None = Field(None, description="What went wrong in this case.")
    instance: str | None = Field(None, description="Path of the request.")
    errors: list[FieldError] | None = Field(None, description="Invalid fields (status 422).")


class ProblemError(Exception):
    """Raised by a router to answer with a problem."""

    def __init__(
        self,
        status: HTTPStatus,
        detail: str | None = None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(detail or status.phrase)
        self.status = status
        self.detail = detail
        self.headers = headers


def problem_response(
    request: Request,
    status: HTTPStatus,
    detail: str | None = None,
    *,
    errors: list[FieldError] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    problem = Problem(
        title=status.phrase,
        status=status.value,
        detail=detail,
        instance=request.url.path,
        errors=errors,
    )
    return JSONResponse(
        problem.model_dump(exclude_none=True),
        status_code=status.value,
        media_type=MEDIA_TYPE,
        headers=headers,
    )


def responses(*statuses: HTTPStatus) -> dict[int | str, dict[str, Any]]:
    """OpenAPI entries for the problems a route answers with, for `responses=`."""
    return {
        status.value: {
            "description": status.phrase,
            "model": Problem,
            "content": {MEDIA_TYPE: {}},
        }
        for status in statuses
    }


def allowed_methods(app: FastAPI, path: str) -> list[str]:
    """Methods the OpenAPI document lists for `path`.

    FastAPI makes one route per method, and Starlette's own `Allow` names only
    the methods of the first route that matches the path.
    """
    methods: set[str] = set()
    for template, operations in app.openapi().get("paths", {}).items():
        pattern = re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(template))
        if re.fullmatch(pattern, path):
            methods.update(method.upper() for method in operations)
    return sorted(methods)


def install(app: FastAPI) -> None:
    """Answer every error of `app` with a problem."""

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        status = HTTPStatus(error.status_code)
        detail = error.detail if error.detail != status.phrase else None
        headers = {name.lower(): value for name, value in (error.headers or {}).items()}
        if status is HTTPStatus.METHOD_NOT_ALLOWED and (
            methods := allowed_methods(app, request.url.path)
        ):
            headers["allow"] = ", ".join(methods)
        return problem_response(request, status, detail, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        errors = [
            FieldError(location=list(item["loc"]), message=item["msg"], type=item["type"])
            for item in error.errors()
        ]
        return problem_response(
            request,
            HTTPStatus.UNPROCESSABLE_CONTENT,
            "The request has invalid fields.",
            errors=errors,
        )

    @app.exception_handler(ProblemError)
    async def problem(request: Request, error: ProblemError) -> JSONResponse:
        return problem_response(request, error.status, error.detail, headers=error.headers)

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError) -> JSONResponse:
        if isinstance(error, NotFoundError):
            status = HTTPStatus.NOT_FOUND
        elif isinstance(error, ConflictError):
            status = HTTPStatus.CONFLICT
        else:
            status = HTTPStatus.BAD_REQUEST
        return problem_response(request, status, str(error))

    @app.exception_handler(APIError)
    async def upstream_error(request: Request, error: APIError) -> JSONResponse:
        # An LLM, embedding or other API failed after its retries.
        log.warning("upstream API failed", path=request.url.path, error=str(error))
        return problem_response(request, HTTPStatus.BAD_GATEWAY, str(error))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        # Logged with the traceback; the client only learns that it failed.
        log.error("request failed", path=request.url.path, exc_info=error)
        return problem_response(request, HTTPStatus.INTERNAL_SERVER_ERROR)
