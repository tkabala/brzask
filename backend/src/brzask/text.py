"""Small text and date helpers for content that comes from feeds and pages."""

import calendar
import html
import re
import time
from datetime import UTC, datetime, timedelta

_SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]*>")
_UNCLOSED_TAG = re.compile(r"<[^>]*$")
_SPACE = re.compile(r"\s+")

# Feeds with clocks or time zones set wrong date entries hours ahead; anything
# further ahead than this is treated as an unknown date rather than trusted.
MAX_FUTURE = timedelta(days=1)


def strip_html(value: str | None) -> str:
    """Plain text from an HTML fragment, with whitespace collapsed.

    Feed content is often raw HTML (link tables, release-note lists). It must
    be cleaned before it is cut to length, or prompts get markup instead of
    text; a tag left open by an earlier cut is removed as well.
    """
    text = _SCRIPT.sub(" ", value or "")
    text = _TAG.sub(" ", text)
    text = _UNCLOSED_TAG.sub(" ", text)
    return _SPACE.sub(" ", html.unescape(text)).strip()


def from_struct_time(value: time.struct_time | None, now: datetime) -> datetime | None:
    """A UTC datetime from a parsed feed date, or None when it is missing or implausible.

    Unknown dates are kept as None instead of guessed, so later stages can
    decide (an article with an unknown date is not dropped as stale).
    """
    if value is None:
        return None
    try:
        moment = datetime.fromtimestamp(calendar.timegm(value), UTC)
    except (OverflowError, ValueError, OSError):
        return None
    return None if moment > now + MAX_FUTURE else moment
