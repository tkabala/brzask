"""Fetches through a fake proxy on loopback that records what it is asked to
reach and answers as each test scripts it."""

import socket
import socketserver
import struct
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import httpx2
import pytest

from brzask.clients.http import public_client
from brzask.clients.tunnel import parse_proxy

TIMEOUT = httpx2.Timeout(5.0)
EXAMPLE = {"example.test": ["93.184.216.34"], "v6.test": ["2606:2800:220:1::248"]}
OK = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"


def resolve(host: str, port: int) -> list[str]:
    return {**EXAMPLE, "intranet.test": ["10.0.0.5"], "lan.test": ["192.168.1.10"]}.get(
        host, [host]
    )


@dataclass
class Script:
    """What the fake proxy answers; it records every request it gets."""

    # The CONNECT reply status line, or the SOCKS5 reply code.
    reply: bytes | int = b"HTTP/1.1 200 Connection established"
    # "close": close right after the request; "silent": never answer.
    behaviour: str = "answer"
    # The tunnelled server's answer.
    response: bytes = OK
    connections: int = 0
    requests: list[bytes] = field(default_factory=list)
    released: threading.Event = field(default_factory=threading.Event)


def _read_until(sock: socket.socket, marker: bytes) -> bytes:
    data = b""
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


def _read_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            break
        data += chunk
    return data


class HttpProxy(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        script = self.server.script  # type: ignore[attr-defined]
        script.connections += 1
        sock: socket.socket = self.request
        script.requests.append(_read_until(sock, b"\r\n\r\n"))
        if script.behaviour == "silent":
            script.released.wait(10)
            return
        if script.behaviour == "close":
            return
        sock.sendall(script.reply + b"\r\n\r\n")
        _read_until(sock, b"\r\n\r\n")
        sock.sendall(script.response)


class SocksProxy(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        script = self.server.script  # type: ignore[attr-defined]
        script.connections += 1
        sock: socket.socket = self.request
        _version, count = _read_exact(sock, 2)
        methods = _read_exact(sock, count)
        if b"\x02" in methods:
            sock.sendall(b"\x05\x02")
            _version, size = _read_exact(sock, 2)
            user = _read_exact(sock, size)
            (size,) = _read_exact(sock, 1)
            password = _read_exact(sock, size)
            script.requests.append(b"auth " + user + b":" + password)
            sock.sendall(b"\x01\x00")
        else:
            sock.sendall(b"\x05\x00")
        header = _read_exact(sock, 4)
        size = {1: 4, 4: 16}.get(header[3], 0)
        request = header + _read_exact(sock, size + 2)
        script.requests.append(request)
        if script.behaviour == "close":
            return
        assert isinstance(script.reply, int)
        sock.sendall(bytes([5, script.reply, 0, 1, 0, 0, 0, 0, 0, 0]))
        if script.reply != 0:
            return
        _read_until(sock, b"\r\n\r\n")
        sock.sendall(script.response)


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, handler: type[socketserver.BaseRequestHandler], script: Script) -> None:
        super().__init__(("127.0.0.1", 0), handler)
        self.script = script

    @property
    def port(self) -> int:
        return int(self.server_address[1])


def _serve(handler: type[socketserver.BaseRequestHandler], script: Script) -> Iterator[Server]:
    server = Server(handler, script)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        script.released.set()
        server.shutdown()
        server.server_close()


@pytest.fixture
def script() -> Script:
    return Script()


@pytest.fixture
def http_proxy(script: Script) -> Iterator[Server]:
    yield from _serve(HttpProxy, script)


@pytest.fixture
def socks_proxy(script: Script) -> Iterator[Server]:
    script.reply = 0
    yield from _serve(SocksProxy, script)


def client(proxy_url: str, timeout: httpx2.Timeout = TIMEOUT) -> httpx2.Client:
    return public_client(timeout, [], resolve=resolve, proxy=parse_proxy(proxy_url))


def test_parse_proxy() -> None:
    target = parse_proxy("http://us%40er:p%3Aw@proxy.lan:3128")

    assert (target.scheme, target.host, target.port) == ("http", "proxy.lan", 3128)
    assert (target.username, target.password) == ("us@er", "p:w")


@pytest.mark.parametrize(
    "url", ["https://h:1", "http://h", "socks4://h:1080", "socks5h://h:1080", "http://:1"]
)
def test_parse_proxy_rejects(url: str) -> None:
    with pytest.raises(ValueError, match="FETCH_PROXY"):
        parse_proxy(url)


def test_http_proxy_is_asked_for_the_checked_ip(http_proxy: Server, script: Script) -> None:
    with client(f"http://127.0.0.1:{http_proxy.port}") as http:
        response = http.get("http://example.test/")

    assert response.text == "ok"
    (request,) = script.requests
    lines = request.decode().split("\r\n")
    assert lines[0] == "CONNECT 93.184.216.34:80 HTTP/1.1"
    assert b"example.test" not in request


def test_http_proxy_gets_ipv6_in_brackets(http_proxy: Server, script: Script) -> None:
    with client(f"http://127.0.0.1:{http_proxy.port}") as http:
        http.get("http://v6.test/")

    assert script.requests[0].startswith(b"CONNECT [2606:2800:220:1::248]:80 HTTP/1.1\r\n")


def test_socks5_request_carries_an_address_not_a_name(socks_proxy: Server, script: Script) -> None:
    with client(f"socks5://127.0.0.1:{socks_proxy.port}") as http:
        response = http.get("http://example.test:8080/")

    assert response.text == "ok"
    (request,) = script.requests
    assert request[:4] == b"\x05\x01\x00\x01"
    assert socket.inet_ntoa(request[4:8]) == "93.184.216.34"
    assert struct.unpack("!H", request[8:10]) == (8080,)


def test_socks5_ipv6_address_type(socks_proxy: Server, script: Script) -> None:
    with client(f"socks5://127.0.0.1:{socks_proxy.port}") as http:
        http.get("http://v6.test/")

    request = script.requests[0]
    assert request[3] == 0x04
    assert socket.inet_ntop(socket.AF_INET6, request[4:20]) == "2606:2800:220:1::248"


def test_socks5_credentials_are_sent(socks_proxy: Server, script: Script) -> None:
    with client(f"socks5://user:pw@127.0.0.1:{socks_proxy.port}") as http:
        http.get("http://example.test/")

    assert script.requests[0] == b"auth user:pw"


def test_private_address_is_refused_before_the_proxy_is_contacted(
    http_proxy: Server, script: Script
) -> None:
    with (
        client(f"http://127.0.0.1:{http_proxy.port}") as http,
        pytest.raises(httpx2.ConnectError, match=r"192\.168\.1\.10 is not public"),
    ):
        http.get("http://lan.test/")

    assert script.connections == 0


def test_redirect_to_a_private_host_is_refused_through_the_proxy(
    http_proxy: Server, script: Script
) -> None:
    script.response = (
        b"HTTP/1.1 302 Found\r\nLocation: http://intranet.test/\r\n"
        b"Content-Length: 0\r\nConnection: close\r\n\r\n"
    )
    with (
        client(f"http://127.0.0.1:{http_proxy.port}") as http,
        pytest.raises(httpx2.ConnectError, match=r"10\.0\.0\.5 is not public"),
    ):
        http.get("http://example.test/")

    assert script.connections == 1


@pytest.mark.parametrize(
    ("scheme", "reply", "behaviour"),
    [
        ("http", b"HTTP/1.1 407 Proxy Authentication Required", "answer"),
        ("http", b"HTTP/1.1 403 Forbidden", "answer"),
        ("http", b"HTTP/1.1 502 Bad Gateway", "answer"),
        ("http", b"garbage", "answer"),
        ("http", b"", "close"),
        ("socks5", 0x05, "answer"),
        ("socks5", 0, "close"),
    ],
)
def test_proxy_refusal_is_a_connect_error(
    script: Script, scheme: str, reply: bytes | int, behaviour: str
) -> None:
    handler = HttpProxy if scheme == "http" else SocksProxy
    script.reply = reply
    script.behaviour = behaviour
    with (
        contextmanager(_serve)(handler, script) as proxy,
        client(f"{scheme}://127.0.0.1:{proxy.port}") as http,
        pytest.raises(httpx2.ConnectError),
    ):
        http.get("http://example.test/")


def test_silent_proxy_times_out(http_proxy: Server, script: Script) -> None:
    script.behaviour = "silent"
    started = time.monotonic()
    with (
        client(f"http://127.0.0.1:{http_proxy.port}", httpx2.Timeout(0.5)) as http,
        pytest.raises((httpx2.ConnectTimeout, httpx2.ConnectError)),
    ):
        http.get("http://example.test/")

    assert time.monotonic() - started < 2


def test_unreachable_proxy_is_a_connect_error() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with client(f"http://127.0.0.1:{port}") as http, pytest.raises(httpx2.ConnectError):
        http.get("http://example.test/")


def test_basic_credentials_are_sent(http_proxy: Server, script: Script) -> None:
    with client(f"http://user:pw@127.0.0.1:{http_proxy.port}") as http:
        http.get("http://example.test/")

    assert b"\r\nProxy-Authorization: Basic dXNlcjpwdw==\r\n" in script.requests[0]


def test_no_credentials_no_header(http_proxy: Server, script: Script) -> None:
    with client(f"http://127.0.0.1:{http_proxy.port}") as http:
        http.get("http://example.test/")

    assert b"Proxy-Authorization" not in script.requests[0]
