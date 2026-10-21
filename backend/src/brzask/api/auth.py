"""Authentication: who may use the API, and logging in and out.

AUTH_MODE=password: a session cookie from `POST /api/v1/auth/login`; requests
that change something also send its CSRF token in `X-CSRF-Token`.
AUTH_MODE=none: everyone who reaches the server may do everything.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import APIKeyCookie
from pydantic import BaseModel, Field

from brzask.api import problems
from brzask.api.deps import NO_NUL, DbSession
from brzask.api.problems import ProblemError
from brzask.config.settings import AuthSettings
from brzask.services import auth

SESSION_COOKIE = "brzask_session"
CSRF_COOKIE = "brzask_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    auto_error=False,
    description="Set by POST /api/v1/auth/login. Requests that change something "
    f"also send the CSRF token in {CSRF_HEADER}.",
)


@dataclass
class Auth:
    """How this process authenticates, from AUTH_* settings."""

    settings: AuthSettings
    throttle: auth.LoginThrottle = field(default_factory=auth.LoginThrottle)

    @property
    def mode(self) -> Literal["password", "header", "none"]:
        return self.settings.mode

    @property
    def secret(self) -> str | None:
        secret = self.settings.session_secret
        return secret.get_secret_value() if secret else None

    def signing_secret(self) -> str:
        """The secret, which the settings require for every mode but none."""
        if self.secret is None:
            raise RuntimeError(f"AUTH_MODE={self.mode} without AUTH_SESSION_SECRET")
        return self.secret

    def password_hash(self) -> str:
        if self.settings.password_hash is None:
            raise RuntimeError("AUTH_MODE=password without AUTH_PASSWORD_HASH")
        return self.settings.password_hash.get_secret_value()

    def open_url(self, article_id: int) -> str:
        """The path that opens an article; signed, so it works without a session."""
        if self.secret is None:
            return f"/open?id={article_id}"
        return f"/open?id={article_id}&sig={auth.link_signature(self.secret, article_id)}"


def get_auth(request: Request) -> Auth:
    current: Auth = request.app.state.auth
    return current


AuthConfig = Annotated[Auth, Depends(get_auth)]
SessionCookie = Annotated[str | None, Depends(session_cookie)]


def require_user(
    request: Request, session: DbSession, config: AuthConfig, token: SessionCookie
) -> None:
    """Let the request through only for a logged-in user (or when AUTH_MODE=none)."""
    if config.mode == "none":
        return
    if token is None or auth.current_login(session, token, datetime.now(UTC)) is None:
        raise ProblemError(HTTPStatus.UNAUTHORIZED, "Log in first.")
    if request.method not in SAFE_METHODS and not auth.csrf_matches(
        config.signing_secret(), token, request.headers.get(CSRF_HEADER)
    ):
        raise ProblemError(
            HTTPStatus.FORBIDDEN, f"Missing or wrong {CSRF_HEADER}; reload and try again."
        )


# --- Routes ------------------------------------------------------------------------

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    password: str = Field(min_length=1, max_length=1000, pattern=NO_NUL)


class SessionOut(BaseModel):
    mode: Literal["password", "header", "none"]
    authenticated: bool = Field(description="Whether this request may use the API.")
    csrf_token: str | None = Field(
        description=f"Send in {CSRF_HEADER} with requests that change something."
    )
    expires_at: datetime | None = None


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_cookies(response: Response, config: Auth, token: str, csrf: str) -> None:
    max_age = int(auth.SESSION_LIFETIME.total_seconds())
    secure = config.settings.cookie_secure
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    # Readable by the page, so it can send the token after a reload.
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, secure=secure, samesite="lax")


@router.post(
    "/login",
    summary="Log in with the password",
    responses=problems.responses(
        HTTPStatus.BAD_REQUEST, HTTPStatus.UNAUTHORIZED, HTTPStatus.TOO_MANY_REQUESTS
    ),
)
def login(
    request: Request,
    response: Response,
    session: DbSession,
    config: AuthConfig,
    credentials: Credentials,
) -> SessionOut:
    """Sets the session cookie. After too many wrong passwords, 429 with Retry-After."""
    if config.mode != "password":
        raise ProblemError(HTTPStatus.BAD_REQUEST, f"AUTH_MODE is {config.mode}: no password.")
    client = _client(request)
    wait = config.throttle.retry_after(client)
    if wait is not None:
        raise ProblemError(
            HTTPStatus.TOO_MANY_REQUESTS,
            "Too many wrong passwords; try again later.",
            headers={"Retry-After": str(wait)},
        )
    if not auth.verify_password(config.password_hash(), credentials.password):
        config.throttle.failed(client)
        raise ProblemError(HTTPStatus.UNAUTHORIZED, "Wrong password.")
    config.throttle.succeeded(client)
    new = auth.log_in(session, datetime.now(UTC))
    csrf = auth.csrf_token(config.signing_secret(), new.token)
    _set_cookies(response, config, new.token, csrf)
    return SessionOut(
        mode=config.mode, authenticated=True, csrf_token=csrf, expires_at=new.expires_at
    )


@router.post(
    "/logout",
    summary="Log out",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_user)],
    responses=problems.responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN),
)
def logout(response: Response, session: DbSession, token: SessionCookie) -> None:
    """Ends the session, here and wherever its cookie was copied."""
    if token is not None:
        auth.log_out(session, token)
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)


@router.get("/session", summary="Whether this browser is logged in")
def get_session_state(request: Request, session: DbSession, config: AuthConfig) -> SessionOut:
    """Never fails: tells the page whether to show the login screen."""
    # Read directly, not as a security dependency: this route needs no login.
    token = request.cookies.get(SESSION_COOKIE)
    if config.mode == "none":
        return SessionOut(mode="none", authenticated=True, csrf_token=None)
    if token is None or config.secret is None:
        return SessionOut(mode=config.mode, authenticated=False, csrf_token=None)
    login = auth.current_login(session, token, datetime.now(UTC))
    if login is None:
        return SessionOut(mode=config.mode, authenticated=False, csrf_token=None)
    return SessionOut(
        mode=config.mode,
        authenticated=True,
        csrf_token=auth.csrf_token(config.secret, token),
        expires_at=login.expires_at,
    )
