"""What every outgoing HTTP request shares: who is asking, and how much to read."""

import httpx2

from brzask import PROJECT_URL, __version__

USER_AGENT = f"brzask/{__version__} (+{PROJECT_URL})"
# The product token sites match in robots.txt.
ROBOTS_AGENT = "brzask"


class ResponseTooLargeError(Exception):
    pass


# What a request can fail with: HTTP and network errors, a body over the limit,
# and URLs httpx2 refuses to send (control characters, a malformed IPv6 host,
# a host name that cannot be IDNA-encoded), which feeds do contain.
REQUEST_ERRORS = (httpx2.HTTPError, httpx2.InvalidURL, UnicodeError, ResponseTooLargeError)


def new_client(timeout: httpx2.Timeout) -> httpx2.Client:
    return httpx2.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT})


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
