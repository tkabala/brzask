"""What every outgoing HTTP request shares: who is asking, and how much to read."""

import httpx2

from brzask import PROJECT_URL, __version__

USER_AGENT = f"brzask/{__version__} (+{PROJECT_URL})"
# The product token sites match in robots.txt.
ROBOTS_AGENT = "brzask"


class ResponseTooLargeError(Exception):
    pass


def new_client(timeout: httpx2.Timeout) -> httpx2.Client:
    return httpx2.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT})


def read_limited(response: httpx2.Response, max_bytes: int) -> bytes:
    """The body of a streamed response, refusing to read more than `max_bytes`."""
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > max_bytes:
            raise ResponseTooLargeError(f"larger than {max_bytes // (1024 * 1024)} MB")
        chunks.append(chunk)
    return b"".join(chunks)
