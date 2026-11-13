import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address, ip_network
from typing import Any

import httpcore2
import httpx2
import pytest

from brzask.clients.http import REQUEST_ERRORS, PublicOnlyBackend, is_allowed, public_client

TIMEOUT = httpx2.Timeout(5.0)
LOOPBACK = [ip_network("127.0.0.0/8")]


@pytest.mark.parametrize(
    ("address", "allowed", "expected"),
    [
        ("8.8.8.8", [], True),
        ("2606:4700:4700::1111", [], True),
        ("::ffff:8.8.8.8", [], True),
        ("10.0.0.5", [], False),
        ("127.0.0.1", [], False),
        ("169.254.169.254", [], False),
        ("100.64.0.1", [], False),
        ("0.0.0.0", [], False),  # noqa: S104
        ("::", [], False),
        ("::1", [], False),
        ("fd00::1", [], False),
        ("::ffff:10.0.0.5", [], False),
        ("192.168.1.7", [ip_network("192.168.1.0/24")], True),
        ("192.168.2.7", [ip_network("192.168.1.0/24")], False),
        ("::ffff:192.168.1.7", [ip_network("192.168.1.0/24")], True),
    ],
)
def test_is_allowed(address: str, allowed: list[Any], expected: bool) -> None:
    assert is_allowed(ip_address(address), allowed) is expected


def answers(table: dict[str, list[str]]) -> Any:
    def resolve(host: str, port: int) -> list[str]:
        return table.get(host, [host])

    return resolve


def test_backend_refuses_private() -> None:
    backend = PublicOnlyBackend([], resolve=answers({"intranet.test": ["10.0.0.5"]}))
    with pytest.raises(
        httpcore2.ConnectError,
        match=r"address 10\.0\.0\.5 is not public \(ALLOWED_PRIVATE_NETWORKS\)",
    ):
        backend.connect_tcp("intranet.test", 80)


def test_backend_refuses_a_mixed_answer() -> None:
    backend = PublicOnlyBackend([], resolve=answers({"both.test": ["93.184.215.14", "10.0.0.5"]}))
    with pytest.raises(httpcore2.ConnectError, match=r"10\.0\.0\.5"):
        backend.connect_tcp("both.test", 80)


def test_backend_refuses_an_empty_answer() -> None:
    backend = PublicOnlyBackend([], resolve=answers({"nothing.test": []}))
    with pytest.raises(httpcore2.ConnectError, match=r"no address for nothing\.test"):
        backend.connect_tcp("nothing.test", 80)


def test_backend_connects_to_the_checked_address(monkeypatch: pytest.MonkeyPatch) -> None:
    connected: list[str] = []

    def connect(self: Any, host: str, port: int, *args: Any, **kwargs: Any) -> Any:
        connected.append(host)
        return object()

    monkeypatch.setattr(httpcore2.SyncBackend, "connect_tcp", connect)
    backend = PublicOnlyBackend([], resolve=answers({"site.test": ["93.184.215.14"]}))
    backend.connect_tcp("site.test", 443)
    assert connected == ["93.184.215.14"]


class Handler(BaseHTTPRequestHandler):
    redirect_to: str | None = None

    def do_GET(self) -> None:
        if self.path == "/redirect" and self.redirect_to:
            self.send_response(302)
            self.send_header("Location", self.redirect_to)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    Handler.redirect_to = None


def test_client_fetches_from_an_allowed_network(server: ThreadingHTTPServer) -> None:
    with public_client(TIMEOUT, LOOPBACK) as client:
        response = client.get(f"http://127.0.0.1:{server.server_port}/")
    assert response.status_code == 200
    assert response.text == "ok"


def test_client_refuses_loopback_by_default(server: ThreadingHTTPServer) -> None:
    with public_client(TIMEOUT, []) as client, pytest.raises(httpx2.ConnectError) as error:
        client.get(f"http://127.0.0.1:{server.server_port}/")
    assert "address 127.0.0.1 is not public" in str(error.value)
    assert isinstance(error.value, REQUEST_ERRORS)


def test_client_refuses_a_redirect_to_a_private_host(server: ThreadingHTTPServer) -> None:
    Handler.redirect_to = f"http://intranet.test:{server.server_port}/"
    resolve = answers({"intranet.test": ["10.0.0.5"]})
    with (
        public_client(TIMEOUT, LOOPBACK, resolve=resolve) as client,
        pytest.raises(httpx2.ConnectError, match=r"address 10\.0\.0\.5 is not public"),
    ):
        client.get(f"http://127.0.0.1:{server.server_port}/redirect")


def test_client_sends_the_user_agent_and_extra_headers(server: ThreadingHTTPServer) -> None:
    with public_client(TIMEOUT, LOOPBACK, headers={"Accept": "application/rss+xml"}) as client:
        assert client.headers["Accept"] == "application/rss+xml"
        assert client.headers["User-Agent"].startswith("brzask/")
        assert client.follow_redirects


def test_backend_tries_the_next_checked_address(monkeypatch: pytest.MonkeyPatch) -> None:
    tried: list[str] = []

    def connect(self: Any, host: str, port: int, *args: Any, **kwargs: Any) -> Any:
        tried.append(host)
        if host == "2606:4700::1":
            raise httpcore2.ConnectError("network unreachable")
        return object()

    monkeypatch.setattr(httpcore2.SyncBackend, "connect_tcp", connect)
    backend = PublicOnlyBackend(
        [], resolve=answers({"dual.test": ["2606:4700::1", "93.184.215.14"]})
    )
    backend.connect_tcp("dual.test", 443)
    assert tried == ["2606:4700::1", "93.184.215.14"]


def test_backend_raises_when_no_checked_address_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(self: Any, host: str, port: int, *args: Any, **kwargs: Any) -> Any:
        raise httpcore2.ConnectError(f"{host} unreachable")

    monkeypatch.setattr(httpcore2.SyncBackend, "connect_tcp", connect)
    backend = PublicOnlyBackend([], resolve=answers({"down.test": ["93.184.215.14", "8.8.8.8"]}))
    with pytest.raises(httpcore2.ConnectError, match=r"8\.8\.8\.8 unreachable"):
        backend.connect_tcp("down.test", 443)
