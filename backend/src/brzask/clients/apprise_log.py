"""Keeping Apprise's own log lines out of brzask's log.

Apprise logs the URLs it loads and posts to, and those carry tokens and
passwords. brzask reports a failed notification itself, by service name.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def quiet_apprise() -> Iterator[None]:
    """Silence the `apprise` logger for the duration of the block."""
    logger = logging.getLogger("apprise")
    previous = logger.level
    logger.setLevel(logging.CRITICAL + 1)
    try:
        yield
    finally:
        logger.setLevel(previous)
