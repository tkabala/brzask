"""Notifications: "digest ready" once a day and "pipeline failed". Nothing else.

Messages go through Apprise to every URL in NOTIFY_URLS. Which runs send one
is decided by `message_after_run`; dry, skipped and interrupted runs never do,
and a forced second digest of the same day does not either. Sending never
raises: a service that is down only costs a warning in the log.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy.orm import Session

from brzask.clients.apprise_log import quiet_apprise
from brzask.config.settings import NotificationSettings
from brzask.db.models import Run, RunKind, RunStatus
from brzask.log import get_logger
from brzask.repositories import RunRepository
from brzask.services.digests import digest_for

log = get_logger(__name__)

ERROR_CHARS = 300  # enough for the exception line; the run row keeps all of it


@dataclass(frozen=True, slots=True)
class Message:
    title: str
    body: str


TEST_MESSAGE = Message("brzask: test notification", "If you can read this, notifications work.")


class Notifier(Protocol):
    def send(self, message: Message) -> bool:
        """Send to every target; False when any of them failed. Never raises."""
        ...


class AppriseNotifier:
    """Sends to Apprise URLs; logs a failure by service name, never by URL."""

    def __init__(self, targets: Sequence[str]) -> None:
        # Imported here: loading Apprise's plugins takes most of a second.
        from apprise import Apprise

        self._apprise = Apprise()
        with quiet_apprise():
            for target in targets:
                self._apprise.add(target)
        self._services = [service.service_name for service in self._apprise]

    def send(self, message: Message) -> bool:
        from apprise import NotifyFormat

        try:
            with quiet_apprise():
                sent = bool(
                    self._apprise.notify(
                        body=message.body, title=message.title, body_format=NotifyFormat.TEXT
                    )
                )
        except Exception as error:
            log.warning(
                "notification not sent", services=self._services, error=type(error).__name__
            )
            return False
        if not sent:
            log.warning("notification not sent", services=self._services)
        return sent


def notifier_from_settings(settings: NotificationSettings) -> Notifier | None:
    """A notifier for NOTIFY_URLS; None when notifications are off."""
    return AppriseNotifier(settings.targets) if settings.targets else None


def digest_ready_message(titles: Sequence[str], public_url: str | None) -> Message:
    count = len(titles)
    title = f"brzask: today's {count} {'is' if count == 1 else 'are'} ready"
    body = "\n".join(f"{n}. {text}" for n, text in enumerate(titles, start=1))
    if public_url:
        body += f"\n\n{public_url}"
    return Message(title, body)


def run_failed_message(
    kind: RunKind, run_id: uuid.UUID, error: str | None, public_url: str | None
) -> Message:
    text = error or "no error recorded"
    if len(text) > ERROR_CHARS:
        text = text[: ERROR_CHARS - 1] + "…"
    lines = [text, f"run {run_id}"]
    if public_url:
        lines.append(f"{public_url}status")
    return Message(f"brzask: {kind.value} run failed", "\n".join(lines))


def message_after_run(session: Session, run: Run, public_url: str | None) -> Message | None:
    """What to send for a finished run, if anything."""
    if run.dry_run:
        return None
    if run.status is RunStatus.FAILED:
        if (run.error or "").startswith("interrupted ("):
            return None  # Ctrl-C or a shutdown: someone did that on purpose
        return run_failed_message(run.kind, run.id, run.error, public_url)
    if run.status is not RunStatus.OK or run.kind is not RunKind.DIGEST:
        return None
    day_text = run.stats.get("date")
    if not isinstance(day_text, str):
        return None
    day = date.fromisoformat(day_text)
    if RunRepository(session).earlier_digest_on(day, run):
        return None  # once a day: a forced second run stays quiet
    articles = digest_for(session, day)
    if not articles:
        return None
    return digest_ready_message(
        [article.digest_title or article.title for article in articles], public_url
    )
