"""Tunnels through the fetch proxy (`FETCH_PROXY`) to an address already checked.

The proxy is only ever asked for an IP address and a port, never a host name,
so it cannot resolve a name to somewhere the address check did not see.
Plain-HTTP targets go through a tunnel too, so the proxy never gets a URL.
"""

import base64
import time
from dataclasses import dataclass
from ipaddress import IPv4Address, ip_address
from typing import Literal
from urllib.parse import unquote, urlsplit

import httpcore2
from socksio import ProtocolError
from socksio.socks5 import (
    SOCKS5AType,
    SOCKS5AuthMethod,
    SOCKS5AuthMethodsRequest,
    SOCKS5AuthReply,
    SOCKS5Command,
    SOCKS5CommandRequest,
    SOCKS5Reply,
    SOCKS5ReplyCode,
    SOCKS5UsernamePasswordReply,
    SOCKS5UsernamePasswordRequest,
)

# A CONNECT reply is a status line and a few headers; anything longer is not one.
MAX_CONNECT_REPLY = 16 * 1024


@dataclass(frozen=True)
class ProxyTarget:
    scheme: Literal["http", "socks5"]
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    def __repr__(self) -> str:
        # Never shows the credentials.
        return f"ProxyTarget({self.scheme}://{self.host}:{self.port})"


def parse_proxy(url: str) -> ProxyTarget:
    """The proxy a `FETCH_PROXY` URL names. Errors never quote the URL, which
    may carry credentials."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "socks5"):
        raise ValueError("FETCH_PROXY must start with http:// or socks5://")
    try:
        port = parts.port
    except ValueError:
        raise ValueError("FETCH_PROXY has an invalid port") from None
    if not parts.hostname or port is None:
        raise ValueError("FETCH_PROXY needs a host and a port, e.g. http://proxy.lan:3128")
    return ProxyTarget(
        scheme="http" if scheme == "http" else "socks5",
        host=parts.hostname,
        port=port,
        username=None if parts.username is None else unquote(parts.username),
        password=None if parts.password is None else unquote(parts.password),
    )


def open_tunnel(
    stream: httpcore2.NetworkStream,
    proxy: ProxyTarget,
    address: str,
    port: int,
    timeout: float | None,
) -> None:
    """Asks the proxy on `stream` to connect to `address` (an IP) and `port`.

    On return the stream carries the connection to the target. Raises
    `httpcore2.ConnectError` when the proxy refuses or answers something
    else, `httpcore2.ConnectTimeout` when it does not answer within `timeout`.
    """
    io = _Io(stream, timeout)
    try:
        if proxy.scheme == "http":
            _http_connect(io, proxy, address, port)
        else:
            _socks5_connect(io, proxy, address, port)
    except (httpcore2.ReadTimeout, httpcore2.WriteTimeout) as error:
        raise httpcore2.ConnectTimeout(f"proxy did not answer: {error}") from error
    except (httpcore2.ReadError, httpcore2.WriteError) as error:
        raise httpcore2.ConnectError(f"proxy connection failed: {error}") from error
    except ProtocolError as error:
        raise httpcore2.ConnectError(f"proxy sent a malformed SOCKS5 reply: {error}") from error


class _Io:
    """Reads and writes on the stream within one deadline for the whole
    exchange, so a proxy answering a byte at a time cannot stretch it."""

    def __init__(self, stream: httpcore2.NetworkStream, timeout: float | None) -> None:
        self.stream = stream
        self.deadline = None if timeout is None else time.monotonic() + timeout

    def _left(self) -> float | None:
        if self.deadline is None:
            return None
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise httpcore2.ReadTimeout("timed out")
        return left

    def write(self, data: bytes) -> None:
        self.stream.write(data, timeout=self._left())

    def read(self, max_bytes: int) -> bytes:
        data = self.stream.read(max_bytes, timeout=self._left())
        if not data:
            raise httpcore2.ConnectError("proxy closed the connection")
        return data

    def read_exactly(self, size: int) -> bytes:
        data = b""
        while len(data) < size:
            data += self.read(size - len(data))
        return data


def _http_connect(io: _Io, proxy: ProxyTarget, address: str, port: int) -> None:
    ip = ip_address(address)
    authority = f"{ip}:{port}" if isinstance(ip, IPv4Address) else f"[{ip}]:{port}"
    lines = [f"CONNECT {authority} HTTP/1.1", f"Host: {authority}"]
    if proxy.username is not None or proxy.password is not None:
        credentials = f"{proxy.username or ''}:{proxy.password or ''}".encode()
        lines.append(f"Proxy-Authorization: Basic {base64.b64encode(credentials).decode()}")
    io.write(("\r\n".join(lines) + "\r\n\r\n").encode())

    reply = b""
    while b"\r\n\r\n" not in reply:
        if len(reply) >= MAX_CONNECT_REPLY:
            raise httpcore2.ConnectError("proxy sent an oversized CONNECT reply")
        reply += io.read(MAX_CONNECT_REPLY - len(reply))
    head, rest = reply.split(b"\r\n\r\n", 1)
    status_line = head.split(b"\r\n", 1)[0].decode("latin-1")
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[0].startswith("HTTP/1."):
        raise httpcore2.ConnectError("proxy sent a malformed CONNECT reply")
    if parts[1] != "200":
        raise httpcore2.ConnectError(f"proxy refused the tunnel: {status_line}")
    if rest:
        # The target speaks only after the client has; bytes here would be lost.
        raise httpcore2.ConnectError("proxy sent data before the tunnel was used")


_SOCKS_ADDRESS_SIZE = {SOCKS5AType.IPV4_ADDRESS: 4, SOCKS5AType.IPV6_ADDRESS: 16}


def _socks5_connect(io: _Io, proxy: ProxyTarget, address: str, port: int) -> None:
    with_credentials = proxy.username is not None or proxy.password is not None
    method = (
        SOCKS5AuthMethod.USERNAME_PASSWORD
        if with_credentials
        else SOCKS5AuthMethod.NO_AUTH_REQUIRED
    )
    io.write(SOCKS5AuthMethodsRequest([method]).dumps())
    if SOCKS5AuthReply.loads(io.read_exactly(2)).method != method:
        raise httpcore2.ConnectError("proxy refused the SOCKS5 authentication method")
    if with_credentials:
        login = SOCKS5UsernamePasswordRequest(
            (proxy.username or "").encode(), (proxy.password or "").encode()
        )
        io.write(login.dumps())
        if not SOCKS5UsernamePasswordReply.loads(io.read_exactly(2)).success:
            raise httpcore2.ConnectError("proxy refused the SOCKS5 credentials")

    ip = ip_address(address)
    # Built by hand rather than from a string, so the address type is always
    # IPv4 or IPv6 and never a domain name.
    request = SOCKS5CommandRequest(
        command=SOCKS5Command.CONNECT,
        atype=SOCKS5AType.IPV4_ADDRESS if ip.version == 4 else SOCKS5AType.IPV6_ADDRESS,
        addr=ip.packed,
        port=port,
    )
    io.write(request.dumps())

    head = io.read_exactly(4)
    if head[0:1] != b"\x05":
        raise httpcore2.ConnectError("proxy sent a malformed SOCKS5 reply")
    if head[1:2] != SOCKS5ReplyCode.SUCCEEDED:
        raise httpcore2.ConnectError(f"proxy refused the tunnel: SOCKS5 reply {head[1]:#04x}")
    try:
        atype = SOCKS5AType(head[3:4])
    except ValueError:
        raise httpcore2.ConnectError("proxy sent a malformed SOCKS5 reply") from None
    if atype == SOCKS5AType.DOMAIN_NAME:
        size = io.read_exactly(1)
        bound = size + io.read_exactly(size[0] + 2)
    else:
        bound = io.read_exactly(_SOCKS_ADDRESS_SIZE[atype] + 2)
    SOCKS5Reply.loads(head + bound)
