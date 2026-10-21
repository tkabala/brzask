from datetime import UTC, datetime, timedelta
from ipaddress import ip_network

from sqlalchemy.orm import Session

from brzask.services import auth
from brzask.services.auth import (
    FAILURE_WINDOW_SECONDS,
    FAILURES_OVERALL,
    FAILURES_PER_CLIENT,
    LoginThrottle,
)

NOW = datetime(2026, 10, 21, 9, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_password_hashes_verify() -> None:
    hashed = auth.hash_password("secret")

    assert hashed.startswith("$argon2id$")
    assert auth.verify_password(hashed, "secret")
    assert not auth.verify_password(hashed, "Secret")
    assert not auth.verify_password("not a hash", "secret")


def test_csrf_tokens_and_link_signatures_depend_on_the_secret() -> None:
    token = auth.csrf_token("a" * 32, "session")

    assert auth.csrf_matches("a" * 32, "session", token)
    assert not auth.csrf_matches("b" * 32, "session", token)
    assert not auth.csrf_matches("a" * 32, "other", token)
    assert not auth.csrf_matches("a" * 32, "session", None)
    signature = auth.link_signature("a" * 32, 7)
    assert len(signature) == 16
    assert auth.link_signature_matches("a" * 32, 7, signature)
    assert not auth.link_signature_matches("a" * 32, 8, signature)
    # A CSRF token is no link signature for the same value, and back.
    assert not auth.link_signature_matches("a" * 32, 7, auth.csrf_token("a" * 32, "7")[:16])


def test_throttle_locks_a_client_after_its_failures() -> None:
    clock = Clock()
    throttle = LoginThrottle(clock=clock)

    for _ in range(FAILURES_PER_CLIENT - 1):
        throttle.failed("a")
    assert throttle.retry_after("a") is None
    throttle.failed("a")

    assert throttle.retry_after("a") == FAILURE_WINDOW_SECONDS + 1
    assert throttle.retry_after("b") is None
    clock.now += FAILURE_WINDOW_SECONDS
    assert throttle.retry_after("a") is None


def test_the_window_slides() -> None:
    clock = Clock()
    throttle = LoginThrottle(clock=clock)
    for _ in range(FAILURES_PER_CLIENT):
        throttle.failed("a")
        clock.now += 60

    # The oldest failure leaves the window first, and one more lets the client in.
    wait = throttle.retry_after("a")
    assert wait is not None
    clock.now += wait
    assert throttle.retry_after("a") is None


def test_success_clears_a_client_but_not_the_overall_count() -> None:
    clock = Clock()
    throttle = LoginThrottle(clock=clock)
    for n in range(FAILURES_OVERALL):
        throttle.failed(f"client-{n % 10}")
    throttle.succeeded("client-0")

    assert throttle.retry_after("client-0") is not None
    assert throttle.retry_after("someone-new") is not None


def test_sessions(session: Session) -> None:
    new = auth.log_in(session, NOW)

    assert new.expires_at == NOW + auth.SESSION_LIFETIME
    login = auth.current_login(session, new.token, NOW)
    assert login is not None
    assert login.token_hash != new.token
    assert login.last_used_at == NOW
    assert auth.current_login(session, new.token, NOW + auth.SESSION_LIFETIME) is None
    assert auth.log_out(session, new.token)
    assert auth.current_login(session, new.token, NOW) is None
    assert not auth.log_out(session, new.token)


def test_last_use_is_written_now_and_then(session: Session) -> None:
    new = auth.log_in(session, NOW)
    auth.current_login(session, new.token, NOW)

    soon = auth.current_login(session, new.token, NOW + timedelta(minutes=5))
    later = auth.current_login(session, new.token, NOW + auth.TOUCH_INTERVAL)

    assert soon is not None and later is not None
    assert later.last_used_at == NOW + auth.TOUCH_INTERVAL


def test_logging_in_clears_expired_sessions(session: Session) -> None:
    old = auth.log_in(session, NOW - auth.SESSION_LIFETIME - timedelta(1))
    auth.log_in(session, NOW)

    assert not auth.log_out(session, old.token)


def test_non_ascii_tokens_simply_do_not_match() -> None:
    assert not auth.csrf_matches("a" * 32, "session", "\x80é")
    assert not auth.link_signature_matches("a" * 32, 7, "\x80")


PROXIES = [ip_network("10.0.0.0/24"), ip_network("fd00::/64")]


def test_trusted_peers() -> None:
    assert auth.is_trusted("10.0.0.5", PROXIES)
    assert auth.is_trusted("::ffff:10.0.0.5", PROXIES)  # IPv4 on an IPv6 socket
    assert auth.is_trusted("fd00::1", PROXIES)
    assert not auth.is_trusted("10.0.1.5", PROXIES)
    assert not auth.is_trusted("testclient", PROXIES)
    assert not auth.is_trusted(None, PROXIES)
    assert not auth.is_trusted("10.0.0.5", [])


def test_client_address_behind_trusted_proxies() -> None:
    # Directly connected: the peer, whatever the header says.
    assert auth.client_address("203.0.113.9", "1.2.3.4", PROXIES) == "203.0.113.9"
    # Through a proxy: the last hop that is not a proxy; a forged first entry is ignored.
    assert auth.client_address("10.0.0.5", "6.6.6.6, 203.0.113.9", PROXIES) == "203.0.113.9"
    assert auth.client_address("10.0.0.5", "203.0.113.9, 10.0.0.7", PROXIES) == "203.0.113.9"
    assert auth.client_address("10.0.0.5", None, PROXIES) == "10.0.0.5"
    assert auth.client_address("10.0.0.5", "10.0.0.7", PROXIES) == "10.0.0.7"
    assert auth.client_address(None, None, PROXIES) == "unknown"


def test_header_csrf_tokens_differ_from_session_ones() -> None:
    assert auth.header_csrf_token("a" * 32, "alice") != auth.header_csrf_token("a" * 32, "bob")
    assert auth.header_csrf_token("a" * 32, "alice") != auth.csrf_token("a" * 32, "alice")
