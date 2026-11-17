"""YouTube videos read from their captions.

A video page has no article text; its caption track does. A manually uploaded
track is preferred over YouTube's speech recognition, English over other
languages, and the library's machine translations are never asked for: a
model reads the original language fine.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import requests
from youtube_transcript_api import (
    RequestBlocked,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
from youtube_transcript_api.proxies import GenericProxyConfig

from brzask.clients.extractors.base import (
    Extracted,
    ExtractionBlockedError,
    ExtractionError,
    ExtractionInput,
)
from brzask.clients.tunnel import ProxyTarget
from brzask.urls import youtube_video_id

# The library sets no timeout of its own; a request is a page or a small XML file.
TIMEOUT_SECONDS = 30.0
# A new paragraph, with its time marker, about this often.
PARAGRAPH_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class Line:
    start: float  # seconds from the start of the video
    text: str


class Track(Protocol):
    @property
    def language_code(self) -> str: ...
    @property
    def is_generated(self) -> bool: ...


class _Snippet(Protocol):
    @property
    def start(self) -> float: ...
    @property
    def text(self) -> str: ...


class FetchableTrack(Track, Protocol):
    def fetch(self) -> Iterable[_Snippet]: ...


def choose_track[T: Track](tracks: Sequence[T]) -> T | None:
    """Manual English, manual other, generated English, generated other; None without tracks."""

    def order(track: T) -> tuple[bool, bool]:
        code = track.language_code.lower()
        return track.is_generated, not (code == "en" or code.startswith("en-"))

    return min(tracks, key=order, default=None)


def _marker(seconds: float, hours: bool) -> str:
    total = int(seconds)
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"[{h}:{m:02d}:{s:02d}]" if hours else f"[{m:02d}:{s:02d}]"


def format_transcript(lines: Sequence[Line]) -> str:
    """Lines joined into paragraphs of about PARAGRAPH_SECONDS, each starting with
    its time (`[mm:ss]`, or `[h:mm:ss]` in a video longer than an hour), so a
    reader can point to a moment of the video."""
    kept = [(line.start, " ".join(line.text.split())) for line in lines]
    kept = [(start, text) for start, text in kept if text]
    if not kept:
        return ""
    hours = max(start for start, _ in kept) >= 3600
    paragraphs: list[tuple[float, list[str]]] = []
    for start, text in kept:
        if not paragraphs or start - paragraphs[-1][0] >= PARAGRAPH_SECONDS:
            paragraphs.append((start, []))
        paragraphs[-1][1].append(text)
    return "\n\n".join(f"{_marker(start, hours)} {' '.join(texts)}" for start, texts in paragraphs)


def captions(tracks: Iterable[FetchableTrack]) -> list[Line] | None:
    """The lines of the best track in a video's list; None when it has none."""
    track = choose_track(list(tracks))
    if track is None:
        return None
    return [Line(snippet.start, snippet.text) for snippet in track.fetch()]


def proxy_url(proxy: ProxyTarget) -> str:
    """`proxy` as a URL for requests; credentials percent-encoded.

    A SOCKS proxy resolves the host name itself (`socks5h`), as an HTTP proxy
    does for CONNECT, so captions are fetched as seen from the proxy's network.
    """
    auth = ""
    if proxy.username is not None:
        auth = quote(proxy.username, safe="")
        if proxy.password is not None:
            auth += ":" + quote(proxy.password, safe="")
        auth += "@"
    host = f"[{proxy.host}]" if ":" in proxy.host else proxy.host
    scheme = "socks5h" if proxy.scheme == "socks5" else proxy.scheme
    return f"{scheme}://{auth}{host}:{proxy.port}"


class _Session(requests.Session):
    """A requests session with a default timeout."""

    def request(self, *args: Any, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", TIMEOUT_SECONDS)
        return super().request(*args, **kwargs)


def _library_fetch(proxy: ProxyTarget | None) -> Callable[[str], Sequence[Line] | None]:
    def fetch(video_id: str) -> Sequence[Line] | None:
        config = None
        if proxy is not None:
            url = proxy_url(proxy)
            config = GenericProxyConfig(http_url=url, https_url=url)
        # The library's client is not thread-safe; one per video.
        with _Session() as session:
            api = YouTubeTranscriptApi(proxy_config=config, http_client=session)
            return captions(api.list(video_id))

    return fetch


class YouTubeExtractor:
    """A video's captions as its text, with a time marker on every paragraph.

    Goes through `FETCH_PROXY` when one is set: YouTube refuses captions to
    many hosted servers. youtube.com is a public site, so the proxy is handed
    to the library as it is, without brzask's own address check.

    robots.txt is checked for the video page, which it allows. The caption
    endpoints the library calls (`/youtubei/`, `/api/timedtext`) are disallowed
    there for all agents; brzask reads them anyway, once per candidate video,
    as a viewer's player does when it shows the captions.
    """

    name = "youtube"
    fetches_page = True

    def __init__(
        self,
        proxy: ProxyTarget | None,
        fetch: Callable[[str], Sequence[Line] | None] | None = None,
    ) -> None:
        self.proxy = proxy
        self._fetch = fetch or _library_fetch(proxy)

    def extract(self, item: ExtractionInput) -> Extracted | None:
        video_id = youtube_video_id(item.url)
        if video_id is None:
            return None
        try:
            lines = self._fetch(video_id)
        except TranscriptsDisabled:
            return None
        except RequestBlocked as error:
            raise ExtractionBlockedError(f"captions: {type(error).__name__}") from error
        except Exception as error:
            # Anything else the library raises: its own errors, network errors,
            # and whatever parsing YouTube's pages and XML runs into when their
            # shape changes (IndexError, AttributeError, ...). Only an
            # ExtractionError may leave an extractor, or one video would stop
            # the digest. The class name alone: the library's messages are a
            # page of advice, and network errors may quote the proxy URL with
            # its credentials.
            raise ExtractionError(f"captions: {type(error).__name__}") from error
        if not lines:
            return None
        return Extracted(format_transcript(lines))
