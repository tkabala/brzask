import time
from datetime import UTC, datetime

import pytest

from brzask.text import from_struct_time, strip_html

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)


@pytest.mark.parametrize(
    ("html", "text"),
    [
        ("<p>Hello <b>world</b></p>", "Hello world"),
        ("a &amp; b &lt;c&gt;", "a & b <c>"),
        ("<script>alert(1)</script>Text<style>p{}</style>", "Text"),
        ("<SCRIPT type='x'>x</SCRIPT >after", "after"),
        ("Cut in the middle of <a href='https://exa", "Cut in the middle of"),
        ("  lots \n\n of\t space ", "lots of space"),
        ("", ""),
        (None, ""),
    ],
)
def test_strip_html(html: str | None, text: str) -> None:
    assert strip_html(html) == text


def struct(moment: datetime) -> time.struct_time:
    return moment.utctimetuple()


def test_from_struct_time() -> None:
    assert from_struct_time(struct(datetime(2026, 10, 17, 6, tzinfo=UTC)), NOW) == datetime(
        2026, 10, 17, 6, tzinfo=UTC
    )
    assert from_struct_time(None, NOW) is None


def test_dates_far_in_the_future_are_unknown() -> None:
    soon = datetime(2026, 10, 18, 20, tzinfo=UTC)  # a feed a few hours ahead
    later = datetime(2026, 10, 20, tzinfo=UTC)

    assert from_struct_time(struct(soon), NOW) == soon
    assert from_struct_time(struct(later), NOW) is None


def test_impossible_dates_are_unknown() -> None:
    assert from_struct_time(time.struct_time((99999, 1, 1, 0, 0, 0, 0, 1, 0)), NOW) is None
