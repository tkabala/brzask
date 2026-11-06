"""Keeping Apprise's log lines, and those of the HTTP libraries it uses, out of brzask's log.

Apprise logs the URLs it loads and posts to, and urllib3 logs each request's
path at DEBUG; those carry tokens and passwords. brzask reports a failed
notification itself, by service name. Notifications are sent after a run,
when nothing else of brzask is fetching, so silencing these loggers then
hides nothing else. `apprise_active()` tells the Sentry hook to drop the HTTP
breadcrumbs of these requests, which hold the same URLs.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

LOGGERS = ("apprise", "urllib3", "requests", "requests_oauthlib", "oauthlib")
# Process-wide, not a context variable: Apprise may send from threads of its own.
_active = 0


def apprise_active() -> bool:
    """Whether Apprise is at work in some `quiet_apprise` block right now."""
    return _active > 0


@contextmanager
def quiet_apprise() -> Iterator[None]:
    """Silence Apprise and its HTTP libraries for the duration of the block."""
    global _active
    loggers = [logging.getLogger(name) for name in LOGGERS]
    previous = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.CRITICAL + 1)
    _active += 1
    try:
        yield
    finally:
        _active -= 1
        for logger, level in zip(loggers, previous, strict=True):
            logger.setLevel(level)
