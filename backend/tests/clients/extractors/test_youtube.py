from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from youtube_transcript_api import (
    IpBlocked,
    RequestBlocked,
    TranscriptList,
    TranscriptsDisabled,
    VideoUnavailable,
)

from brzask.clients.extractors import ExtractionBlockedError, ExtractionError, ExtractionInput
from brzask.clients.extractors.youtube import (
    Line,
    YouTubeExtractor,
    captions,
    choose_track,
    format_transcript,
    proxy_url,
)
from brzask.clients.tunnel import ProxyTarget

VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
LINES = [Line(float(n * 5), f"Sentence number {n} of the talk.") for n in range(60)]


@dataclass(frozen=True)
class Track:
    language_code: str
    is_generated: bool


def test_format_transcript_marks_every_thirty_seconds() -> None:
    lines = [
        Line(0, "Hello."),
        Line(10, "Welcome."),
        Line(31, "First point."),
        Line(45, "Second point."),
        Line(3605, "Goodbye."),
    ]

    assert format_transcript(lines) == (
        "[0:00:00] Hello. Welcome.\n\n[0:00:31] First point. Second point.\n\n[1:00:05] Goodbye."
    )
    assert format_transcript(lines[:-1]) == (
        "[00:00] Hello. Welcome.\n\n[00:31] First point. Second point."
    )


def test_format_transcript_joins_broken_lines_and_drops_empty_ones() -> None:
    lines = [Line(0, "two\nlines "), Line(2, "  "), Line(4, "end")]

    assert format_transcript(lines) == "[00:00] two lines end"
    assert format_transcript([]) == ""


@pytest.mark.parametrize(
    ("tracks", "chosen"),
    [
        ([Track("pl", True), Track("de", False), Track("en", False)], Track("en", False)),
        ([Track("en", True), Track("de", False)], Track("de", False)),
        ([Track("de", True), Track("en-US", True)], Track("en-US", True)),
        ([Track("pl", True)], Track("pl", True)),
        ([Track("en-GB", False), Track("en", True)], Track("en-GB", False)),
        ([], None),
    ],
)
def test_choose_track_prefers_manual_then_english(
    tracks: list[Track], chosen: Track | None
) -> None:
    assert choose_track(tracks) == chosen


def extractor(result: Sequence[Line] | Exception | None) -> YouTubeExtractor:
    def fetch(video_id: str) -> Sequence[Line] | None:
        assert video_id == "dQw4w9WgXcQ"
        if isinstance(result, Exception):
            raise result
        return result

    return YouTubeExtractor(None, fetch=fetch)


def test_captions_are_the_text() -> None:
    extracted = extractor(LINES).extract(ExtractionInput(VIDEO))

    assert extracted is not None
    assert extracted.text.startswith("[00:00] Sentence number 0 of the talk.")
    assert "\n\n[00:30] Sentence number 6" in extracted.text


@pytest.mark.parametrize("error", [RequestBlocked("dQw4w9WgXcQ"), IpBlocked("dQw4w9WgXcQ")])
def test_blocked_is_reported_as_blocked(error: Exception) -> None:
    with pytest.raises(ExtractionBlockedError):
        extractor(error).extract(ExtractionInput(VIDEO))


@pytest.mark.parametrize(
    "error",
    [VideoUnavailable("dQw4w9WgXcQ"), ConnectionError("reset"), ValueError("bad XML")],
)
def test_other_library_errors_are_extraction_errors(error: Exception) -> None:
    with pytest.raises(ExtractionError) as raised:
        extractor(error).extract(ExtractionInput(VIDEO))

    assert not isinstance(raised.value, ExtractionBlockedError)


def test_no_tracks_is_empty() -> None:
    assert extractor(None).extract(ExtractionInput(VIDEO)) is None
    assert extractor([]).extract(ExtractionInput(VIDEO)) is None
    assert extractor(TranscriptsDisabled("dQw4w9WgXcQ")).extract(ExtractionInput(VIDEO)) is None


@pytest.mark.parametrize(
    "url", ["https://www.youtube.com/@example/videos", "https://blog.example.com/post"]
)
def test_non_video_url_is_empty(url: str) -> None:
    def fetch(video_id: str) -> Sequence[Line] | None:
        raise AssertionError("no video to fetch")

    assert YouTubeExtractor(None, fetch=fetch).extract(ExtractionInput(url)) is None


@pytest.mark.parametrize(
    ("proxy", "url"),
    [
        (ProxyTarget("http", "proxy.lan", 3128), "http://proxy.lan:3128"),
        (
            ProxyTarget("socks5", "proxy.lan", 1080, "us er", "p@ss:word"),
            "socks5h://us%20er:p%40ss%3Aword@proxy.lan:1080",
        ),
        (ProxyTarget("http", "::1", 8888), "http://[::1]:8888"),
    ],
)
def test_proxy_url(proxy: ProxyTarget, url: str) -> None:
    assert proxy_url(proxy) == url


# What a video page carries about its caption tracks, in the shape the library parses.
CAPTIONS_JSON: dict[str, Any] = {
    "captionTracks": [
        {
            "baseUrl": "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=de&kind=asr",
            "name": {"runs": [{"text": "German (auto-generated)"}]},
            "languageCode": "de",
            "kind": "asr",
            "isTranslatable": True,
        },
        {
            "baseUrl": "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=de",
            "name": {"runs": [{"text": "German"}]},
            "languageCode": "de",
            "isTranslatable": True,
        },
    ],
    "translationLanguages": [
        {"languageCode": "en", "languageName": {"runs": [{"text": "English"}]}}
    ],
}
TIMED_TEXT = (
    '<?xml version="1.0" encoding="utf-8" ?><transcript>'
    '<text start="0.5" dur="2">Guten &amp;amp; Tag</text>'
    '<text start="3.1" dur="2">zusammen</text>'
    "</transcript>"
)


class Response:
    status_code = 200
    text = TIMED_TEXT

    def raise_for_status(self) -> None:
        pass


class Client:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str) -> Response:
        self.urls.append(url)
        return Response()


def test_captions_read_the_chosen_track_of_the_library_list() -> None:
    client = Client()
    tracks = TranscriptList.build(client, "dQw4w9WgXcQ", CAPTIONS_JSON)  # type: ignore[arg-type]

    lines = captions(tracks)

    # The manual German track, not the generated one nor a translation to English.
    assert client.urls == ["https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=de"]
    assert lines == [Line(0.5, "Guten & Tag"), Line(3.1, "zusammen")]


def test_captions_of_a_video_without_tracks() -> None:
    tracks = TranscriptList.build(Client(), "dQw4w9WgXcQ", {"captionTracks": []})  # type: ignore[arg-type]

    assert captions(tracks) is None
