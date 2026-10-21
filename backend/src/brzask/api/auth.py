"""Authentication: who may use the API, and logging in and out.

AUTH_MODE=password: a session cookie from `POST /api/v1/auth/login`.
AUTH_MODE=header: the user name in AUTH_HEADER, set by a reverse proxy that
authenticates; believed only from TRUSTED_PROXIES.
AUTH_MODE=none: everyone who reaches the server may do everything.

In the first two, requests that change something also send a CSRF token in
`X-CSRF-Token`: the browser sends the cookies on its own, even for a page on
another site, but that page cannot learn the token. Scripts and agents send an
API token instead (`Authorization: Bearer brz_...`), which no browser sends on
its own, so it needs no CSRF token; a `read` token may only read.
"""

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from brzask.api import problems
from brzask.api.deps import ACTOR, NO_NUL, DbSession, Sessions
from brzask.api.problems import ProblemError
from brzask.config.settings import AuthSettings
from brzask.db.models import TokenScope
from brzask.services import auth, tokens

SESSION_COOKIE = "brzask_session"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

bearer_token = HTTPBearer(
    auto_error=False,
    description="An API token from `brzask tokens create`; a read token may only read.",
)
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
    # One password check at a time: checking the throttle and counting a failure
    # are then one step, so parallel tries cannot all slip under the limit.
    login_lock: threading.Lock = field(default_factory=threading.Lock)

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
Bearer = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_token)]


@dataclass(frozen=True, slots=True)
class Identity:
    """Who a request comes from."""

    actor: str  # as the change log records it: "user", "user:<name>", "token:<name>"
    user: str | None = None  # the proxy's user name (mode header)
    csrf_token: str | None = None  # None when no CSRF check applies (mode none, tokens)
    expires_at: datetime | None = None  # end of a password session
    read_only: bool = False  # a read token


def peer(request: Request) -> str | None:
    """The address the connection comes from, not what any header claims."""
    return request.client.host if request.client else None


def identify(
    request: Request, session: DbSession, config: Auth, token: str | None
) -> Identity | None:
    """Who sent the request, or None when it is not authenticated.

    A brzask token in `Authorization` is judged alone: a wrong token is not
    saved by a session cookie or a proxy's user sent along. Any other
    `Authorization` header belongs to someone else, such as a proxy passing
    on its own credentials, and is ignored.
    """
    if config.mode == "none":
        return Identity(actor=ACTOR)
    bearer = _brzask_token(request.headers.get("authorization", ""))
    if bearer is not None:
        return _token_identity(session, bearer)
    if config.mode == "header":
        if not auth.is_trusted(peer(request), config.settings.trusted_proxies):
            return None
        user = request.headers.get(config.settings.header, "").strip()
        if not user:
            return None
        return Identity(
            f"user:{user}",
            user=user,
            csrf_token=auth.header_csrf_token(config.signing_secret(), user),
        )
    if token is None:
        return None
    login = auth.current_login(session, token, datetime.now(UTC))
    if login is None:
        return None
    return Identity(
        ACTOR,
        csrf_token=auth.csrf_token(config.signing_secret(), token),
        expires_at=login.expires_at,
    )


def _brzask_token(authorization: str) -> str | None:
    """The token in `Bearer brz_...`, or None for any other value."""
    scheme, _, value = authorization.partition(" ")
    value = value.strip()
    if scheme.lower() != "bearer" or not value.startswith(tokens.TOKEN_PREFIX):
        return None
    return value


def _token_identity(session: DbSession, value: str) -> Identity | None:
    token = tokens.authenticate_token(session, value, datetime.now(UTC))
    if token is None:
        return None
    return Identity(f"token:{token.name}", read_only=token.scope is not TokenScope.WRITE)


def require_user(
    request: Request,
    sessions: Sessions,
    config: AuthConfig,
    token: SessionCookie,
    _bearer: Bearer,  # declares the scheme in the document; read in `identify`
) -> None:
    """Let the request through only when it is authenticated (always when AUTH_MODE=none)."""
    # A transaction of its own, committed at once: the route's may last while a
    # site or the embedding API answers, and must not keep the session row
    # locked (its last use may have been written) for that long.
    with sessions.begin() as session:
        identity = identify(request, session, config, token)
    if identity is None:
        if config.mode == "header":
            raise ProblemError(
                HTTPStatus.UNAUTHORIZED,
                f"No {config.settings.header} from a trusted proxy; sign in through it.",
            )
        raise ProblemError(HTTPStatus.UNAUTHORIZED, "Log in first.")
    if identity.read_only and request.method not in SAFE_METHODS:
        raise ProblemError(HTTPStatus.FORBIDDEN, "This token may only read.")
    if (
        identity.csrf_token is not None
        and request.method not in SAFE_METHODS
        and not auth.same_token(identity.csrf_token, request.headers.get(CSRF_HEADER))
    ):
        raise ProblemError(
            HTTPStatus.FORBIDDEN, f"Missing or wrong {CSRF_HEADER}; reload and try again."
        )
    request.state.identity = identity


def get_actor(request: Request) -> str:
    """Who to record changes as; set by `require_user`."""
    identity: Identity = request.state.identity
    return identity.actor


Actor = Annotated[str, Depends(get_actor)]


# --- Routes ------------------------------------------------------------------------

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    password: str = Field(min_length=1, max_length=1000, pattern=NO_NUL)


class SessionOut(BaseModel):
    mode: Literal["password", "header", "none"]
    authenticated: bool = Field(description="Whether this request may use the API.")
    user: str | None = Field(None, description="The user name the proxy sent (mode header).")
    csrf_token: str | None = Field(
        description=f"Send in {CSRF_HEADER} with requests that change something."
    )
    expires_at: datetime | None = None


def _client(request: Request, config: Auth) -> str:
    return auth.client_address(
        peer(request), request.headers.get("X-Forwarded-For"), config.settings.trusted_proxies
    )


def _over_https(request: Request, config: Auth) -> bool:
    """Whether the browser reached us over HTTPS, here or at a trusted proxy."""
    if request.url.scheme == "https":
        return True
    if not auth.is_trusted(peer(request), config.settings.trusted_proxies):
        return False
    # The proxy closest to us wrote the last value.
    forwarded = request.headers.get("X-Forwarded-Proto", "").split(",")[-1].strip()
    return forwarded.lower() == "https"


def _set_cookie(request: Request, response: Response, config: Auth, token: str) -> None:
    max_age = int(auth.SESSION_LIFETIME.total_seconds())
    setting = config.settings.cookie_secure
    # Browsers drop a Secure cookie that arrives over plain HTTP, even from
    # localhost (seen in Chrome 155), so `auto` follows how the request came.
    secure = setting == "true" or (setting == "auto" and _over_https(request, config))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
    )


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
    client = _client(request, config)
    with config.login_lock:
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
    _set_cookie(request, response, config, new.token)
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


@router.get("/session", summary="Whether this browser is logged in")
def get_session_state(request: Request, session: DbSession, config: AuthConfig) -> SessionOut:
    """Never fails: tells the page whether to show the login screen."""
    # Read directly, not as a security dependency: this route needs no login.
    identity = identify(request, session, config, request.cookies.get(SESSION_COOKIE))
    if identity is None:
        return SessionOut(mode=config.mode, authenticated=False, csrf_token=None)
    return SessionOut(
        mode=config.mode,
        authenticated=True,
        user=identity.user,
        csrf_token=identity.csrf_token,
        expires_at=identity.expires_at,
    )
