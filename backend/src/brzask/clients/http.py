"""What every outgoing HTTP request shares: who is asking, how much to read,
and, for URLs third parties name, which addresses may be reached."""

import socket
from collections.abc import Callable, Iterable, Mapping, Sequence
from ipaddress import IPv4Address, IPv6Address, ip_address

import httpcore2
import httpx2

from brzask import PROJECT_URL, __version__
from brzask.config.settings import Network

USER_AGENT = f"brzask/{__version__} (+{PROJECT_URL})"
# The product token sites match in robots.txt.
ROBOTS_AGENT = "brzask"


class ResponseTooLargeError(Exception):
    pass


# What a request can fail with: HTTP and network errors, a body over the limit,
# and URLs httpx2 refuses to send (control characters, a malformed IPv6 host,
# a host name that cannot be IDNA-encoded), which feeds do contain.
REQUEST_ERRORS = (httpx2.HTTPError, httpx2.InvalidURL, UnicodeError, ResponseTooLargeError)


Resolver = Callable[[str, int], list[str]]

# Ends every refusal; httpx2 keeps only the message of a connection error.
NOT_PUBLIC = "is not public (ALLOWED_PRIVATE_NETWORKS)"


def new_client(timeout: httpx2.Timeout) -> httpx2.Client:
    """For services the owner configured (LLM, search, extraction services),
    which may well run on the owner's own network."""
    return httpx2.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT})


def is_allowed(address: IPv4Address | IPv6Address, allowed: Sequence[Network]) -> bool:
    """Whether a fetch of a third-party URL may connect to `address`: a public
    address, or one in a network the owner allowed."""
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global or any(address in network for network in allowed)


class AddressNotAllowedError(Exception):
    """A URL's host resolves to an address `public_client` refuses."""


def is_refused_address(error: Exception) -> bool:
    """Whether a request failed because its address is not allowed."""
    return isinstance(error, httpx2.ConnectError) and NOT_PUBLIC in str(error)


def _resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class PublicOnlyBackend(httpcore2.SyncBackend):
    """Connects only to addresses `is_allowed` accepts.

    The host is resolved once, every address it resolves to is checked, and
    the connection goes to the checked addresses only, so a DNS answer that changes
    between the check and the connection cannot lead elsewhere. TLS still
    verifies the host name.
    """

    def __init__(self, allowed: Sequence[Network], resolve: Resolver = _resolve) -> None:
        self.allowed = tuple(allowed)
        self.resolve = resolve

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.NetworkStream:
        try:
            addresses = self.resolve(host, port)
        except OSError as error:
            raise httpcore2.ConnectError(f"cannot resolve {host}: {error}") from error
        if not addresses:
            raise httpcore2.ConnectError(f"no address for {host}")
        for address in addresses:
            if not is_allowed(ip_address(address), self.allowed):
                raise httpcore2.ConnectError(f"address {address} {NOT_PUBLIC}")
        # Like a connection by name: each address in turn, until one answers.
        for address in addresses[:-1]:
            try:
                return super().connect_tcp(address, port, timeout, local_address, socket_options)
            except (httpcore2.ConnectError, httpcore2.ConnectTimeout):
                continue
        return super().connect_tcp(addresses[-1], port, timeout, local_address, socket_options)


class _PublicTransport(httpx2.HTTPTransport):
    def __init__(self, backend: PublicOnlyBackend) -> None:
        super().__init__()
        # httpx2 takes no network backend, so the pool it built is replaced by
        # an equal one (its default limits) that connects through `backend`.
        self._pool = httpcore2.ConnectionPool(
            ssl_context=httpx2.create_ssl_context(),
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=5.0,
            network_backend=backend,
        )


def public_client(
    timeout: httpx2.Timeout,
    allowed: Sequence[Network],
    *,
    headers: Mapping[str, str] | None = None,
    resolve: Resolver = _resolve,
) -> httpx2.Client:
    """For URLs third parties name (feeds, article pages, robots.txt): refuses
    every non-public address outside `allowed`, on every redirect too.

    It goes direct: HTTP(S)_PROXY from the environment is not used.
    """
    return httpx2.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, **(headers or {})},
        transport=_PublicTransport(PublicOnlyBackend(allowed, resolve)),
    )


def read_limited(response: httpx2.Response, max_bytes: int) -> bytes:
    """The body of a streamed response, refusing to read more than `max_bytes`."""
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > max_bytes:
            raise ResponseTooLargeError(f"larger than {max_bytes // 1024} KiB")
        chunks.append(chunk)
    return b"".join(chunks)
