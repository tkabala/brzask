"""robots.txt checks before an extractor fetches a page, cached per site."""

import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx2

from brzask.clients.http import ROBOTS_AGENT, ResponseTooLargeError, read_limited
from brzask.log import get_logger

log = get_logger(__name__)

# robots.txt changes rarely; one fetch per site per day is enough.
CACHE_SECONDS = 24 * 60 * 60
# RFC 9309 asks crawlers to parse at least 500 KiB.
MAX_BYTES = 512 * 1024
TIMEOUT = httpx2.Timeout(10.0)

ALLOW_ALL = ["User-agent: *", "Disallow:"]
DISALLOW_ALL = ["User-agent: *", "Disallow: /"]


class RobotsPolicy:
    """Answers "may brzask fetch this URL?" following RFC 9309.

    A missing robots.txt (any 4xx) allows everything; a server error or an
    unreachable site disallows everything until the next check.
    """

    def __init__(
        self,
        client: httpx2.Client,
        *,
        agent: str = ROBOTS_AGENT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.agent = agent
        self._clock = clock
        self._cache: dict[str, tuple[float, RobotFileParser]] = {}
        self._lock = threading.Lock()

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            return False
        site = f"{parts.scheme}://{parts.netloc}"
        return self._parser(site).can_fetch(self.agent, url)

    def _parser(self, site: str) -> RobotFileParser:
        with self._lock:
            cached = self._cache.get(site)
            if cached and self._clock() - cached[0] < CACHE_SECONDS:
                return cached[1]
        # Fetched outside the lock; two threads may fetch the same file once, which is harmless.
        parser = self._fetch(site)
        with self._lock:
            self._cache[site] = (self._clock(), parser)
        return parser

    def _fetch(self, site: str) -> RobotFileParser:
        parser = RobotFileParser()
        try:
            with self.client.stream("GET", f"{site}/robots.txt", timeout=TIMEOUT) as response:
                if 400 <= response.status_code < 500:
                    parser.parse(ALLOW_ALL)
                    return parser
                response.raise_for_status()
                body = read_limited(response, MAX_BYTES)
        except (httpx2.HTTPError, ResponseTooLargeError) as error:
            log.warning(
                "robots.txt unavailable, not fetching from site", site=site, error=str(error)
            )
            parser.parse(DISALLOW_ALL)
            return parser
        parser.parse(body.decode("utf-8", errors="replace").splitlines())
        return parser
