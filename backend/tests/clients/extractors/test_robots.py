import httpx2

from brzask.clients.extractors.robots import CACHE_SECONDS, RobotsPolicy

ROBOTS = """
User-agent: *
Disallow: /private/

User-agent: brzask
Disallow: /no-brzask/
"""


class Site:
    def __init__(self, response: httpx2.Response | Exception) -> None:
        self.response = response
        self.fetches: list[str] = []
        self.now = 0.0

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.fetches.append(str(request.url))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def policy(self) -> RobotsPolicy:
        client = httpx2.Client(transport=httpx2.MockTransport(self.handle))
        return RobotsPolicy(client, clock=lambda: self.now)


def test_rules_for_brzask_and_everyone() -> None:
    policy = Site(httpx2.Response(200, text=ROBOTS)).policy()

    assert policy.allowed("https://site.test/blog/post")
    assert not policy.allowed("https://site.test/no-brzask/post")
    # A group naming brzask replaces the `*` group for brzask (RFC 9309).
    assert policy.allowed("https://site.test/private/x")


def test_missing_robots_allows_everything() -> None:
    for status in (404, 410, 403):
        assert Site(httpx2.Response(status)).policy().allowed("https://site.test/any")


def test_server_errors_and_unreachable_sites_disallow() -> None:
    assert not Site(httpx2.Response(503)).policy().allowed("https://site.test/any")
    assert not Site(httpx2.ConnectError("refused")).policy().allowed("https://site.test/any")


def test_robots_is_fetched_once_per_site_and_refreshed_daily() -> None:
    site = Site(httpx2.Response(200, text=ROBOTS))
    policy = site.policy()

    policy.allowed("https://site.test/a")
    policy.allowed("https://site.test/b")
    policy.allowed("http://site.test/a")  # another scheme is another site
    assert site.fetches == ["https://site.test/robots.txt", "http://site.test/robots.txt"]

    site.now = CACHE_SECONDS + 1
    policy.allowed("https://site.test/a")
    assert len(site.fetches) == 3


def test_non_web_urls_are_never_allowed() -> None:
    policy = Site(httpx2.Response(404)).policy()

    assert not policy.allowed("mailto:someone@example.com")
    assert not policy.allowed("file:///etc/passwd")
