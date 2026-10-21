"""Logging in with the password: sessions, CSRF tokens, signed links, throttling.

A session is a random token in an HttpOnly cookie; only its SHA-256 is stored,
so a copy of the database cannot be used to log in, and logging out deletes
it. Requests that change something also send a CSRF token: an HMAC of the
session token under AUTH_SESSION_SECRET, which a page on another site cannot
read or compute. Article links carry an HMAC of the article ID, so they work
from feed readers and mail without a session.
"""

import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.orm import Session

from brzask.db.models import LoginSession
from brzask.repositories import LoginSessionRepository

# How long a login lasts; logging in again starts a new one.
SESSION_LIFETIME = timedelta(days=30)
# A session's last use is written at most this often, not on every request.
TOUCH_INTERVAL = timedelta(hours=1)

# Throttling of failed logins. Chosen, not measured: with argon2 and these
# limits, guessing gets about 80 tries an hour from everywhere together.
FAILURE_WINDOW_SECONDS = 15 * 60
FAILURES_PER_CLIENT = 5
FAILURES_OVERALL = 20

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """An argon2id hash for AUTH_PASSWORD_HASH."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _sign(secret: str, purpose: str, value: str) -> str:
    message = f"{purpose}:{value}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def csrf_token(secret: str, session_token: str) -> str:
    """The CSRF token that goes with a session."""
    return _sign(secret, "csrf", session_token)


def _same(expected: str, sent: str | None) -> bool:
    # Compared as bytes: compare_digest refuses strings with non-ASCII characters.
    return sent is not None and hmac.compare_digest(expected.encode(), sent.encode())


def csrf_matches(secret: str, session_token: str, sent: str | None) -> bool:
    return _same(csrf_token(secret, session_token), sent)


def link_signature(secret: str, article_id: int) -> str:
    """Signs `/open` links; 16 hex characters are 64 bits, plenty against guessing."""
    return _sign(secret, "open", str(article_id))[:16]


def link_signature_matches(secret: str, article_id: int, sent: str | None) -> bool:
    return _same(link_signature(secret, article_id), sent)


@dataclass(frozen=True, slots=True)
class NewLogin:
    token: str  # the cookie value; only its hash is stored
    expires_at: datetime


def log_in(session: Session, now: datetime) -> NewLogin:
    """Start a session; expired ones are cleared on the way."""
    logins = LoginSessionRepository(session)
    logins.delete_expired(now)
    token = secrets.token_urlsafe(32)
    login = logins.add(token_hash(token), now + SESSION_LIFETIME)
    return NewLogin(token, login.expires_at)


def current_login(session: Session, token: str, now: datetime) -> LoginSession | None:
    """The valid session for a cookie value, its last use updated now and then."""
    logins = LoginSessionRepository(session)
    login = logins.find_valid(token_hash(token), now)
    if login is not None and (
        login.last_used_at is None or now - login.last_used_at >= TOUCH_INTERVAL
    ):
        logins.touch(login, now)
    return login


def log_out(session: Session, token: str) -> bool:
    """End a session. False when there was none."""
    return LoginSessionRepository(session).delete(token_hash(token))


@dataclass
class LoginThrottle:
    """Counts failed logins in a sliding window, per client and overall.

    Kept in memory: a restart forgets it, which only gives back a few tries.
    """

    clock: Callable[[], float] = time.monotonic
    _failures: dict[str, deque[float]] = field(default_factory=dict)
    _all: deque[float] = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def retry_after(self, client: str) -> int | None:
        """Seconds until `client` may try again, or None when it may now."""
        with self._lock:
            now = self.clock()
            self._expire(now)
            waits = []
            mine = self._failures.get(client)
            if mine is not None and len(mine) >= FAILURES_PER_CLIENT:
                waits.append(mine[-FAILURES_PER_CLIENT] + FAILURE_WINDOW_SECONDS - now)
            if len(self._all) >= FAILURES_OVERALL:
                waits.append(self._all[-FAILURES_OVERALL] + FAILURE_WINDOW_SECONDS - now)
            return max(1, int(max(waits)) + 1) if waits else None

    def failed(self, client: str) -> None:
        with self._lock:
            now = self.clock()
            self._failures.setdefault(client, deque()).append(now)
            self._all.append(now)

    def succeeded(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)

    def _expire(self, now: float) -> None:
        cutoff = now - FAILURE_WINDOW_SECONDS
        while self._all and self._all[0] <= cutoff:
            self._all.popleft()
        for client in list(self._failures):
            failures = self._failures[client]
            while failures and failures[0] <= cutoff:
                failures.popleft()
            if not failures:
                del self._failures[client]
