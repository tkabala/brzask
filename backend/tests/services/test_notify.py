import logging
import uuid
from datetime import UTC, date, datetime, timedelta

import apprise
import pytest
from structlog.testing import capture_logs

from brzask.config.settings import NotificationSettings
from brzask.db.models import RunKind, RunStatus
from brzask.services.notify import (
    AppriseNotifier,
    Message,
    digest_ready_message,
    message_after_run,
    notifier_from_settings,
    run_failed_message,
)
from tests.factories import Factories

RUN_ID = uuid.UUID("0b6f1c2e-6a59-4a0f-9a55-3c1e0f6a7d10")
DAY = date(2026, 11, 6)
NOW = datetime(2026, 11, 6, 6, tzinfo=UTC)

# --- Messages ------------------------------------------------------------------------


def test_ready_message_lists_titles_in_order() -> None:
    titles = list("ABCDEFG")

    message = digest_ready_message(titles, "https://home.example/brzask/")

    assert message == Message(
        "brzask: today's 7 are ready",
        "1. A\n2. B\n3. C\n4. D\n5. E\n6. F\n7. G\n\nhttps://home.example/brzask/",
    )


def test_ready_message_for_one_article_and_no_base_url() -> None:
    assert digest_ready_message(["A"], None) == Message("brzask: today's 1 is ready", "1. A")


def test_failed_message_cuts_long_errors() -> None:
    message = run_failed_message(RunKind.DISCOVERY, RUN_ID, "x" * 400, "https://h/")

    assert message.title == "brzask: discovery run failed"
    first, *rest = message.body.split("\n")
    assert len(first) == 300
    assert first.endswith("…")
    assert rest == [f"run {RUN_ID}", "https://h/status"]


def test_failed_message_without_base_url() -> None:
    message = run_failed_message(RunKind.REVIEW, RUN_ID, "RuntimeError: x", None)

    assert message.body == f"RuntimeError: x\nrun {RUN_ID}"


# --- Notifier --------------------------------------------------------------------------


def test_notifier_is_none_when_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFY_URLS", "")

    assert notifier_from_settings(NotificationSettings()) is None


def test_apprise_notifier_reports_failure_without_urls(caplog: pytest.LogCaptureFixture) -> None:
    # Port 9 (discard) is closed on the test machine: the post fails at once.
    notifier = AppriseNotifier(["json://127.0.0.1:9/secret-abc"])

    with caplog.at_level(logging.DEBUG), capture_logs() as logs:
        sent = notifier.send(Message("t", "b"))

    assert sent is False
    assert "secret-abc" not in caplog.text + str(logs)
    assert logs == [
        {
            "event": "notification not sent",
            "failed": [{"entry": 1, "service": "JSON", "status": "failure"}],
            "log_level": "warning",
        }
    ]


def test_apprise_notifier_survives_an_exception(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def explode(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("boom")

    monkeypatch.setattr(apprise.Apprise, "notify", explode)

    assert AppriseNotifier(["ntfys://ntfy.sh/secret-topic"]).send(Message("t", "b")) is False
    assert "secret-topic" not in caplog.text


def test_one_dead_target_does_not_stop_the_other(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    def fake_send(self: object, body: str, title: str = "", **_kwargs: object) -> bool:
        sent.append(type(self).__name__)
        return type(self).__name__ == "NotifyJSON"

    monkeypatch.setattr("apprise.plugins.custom_json.NotifyJSON.send", fake_send)
    monkeypatch.setattr("apprise.plugins.ntfy.NotifyNtfy.send", fake_send)
    notifier = AppriseNotifier(["ntfys://ntfy.sh/topic", "json://localhost/hook"])

    assert notifier.send(Message("t", "b")) is False
    assert sorted(sent) == ["NotifyJSON", "NotifyNtfy"]


# --- Which runs notify --------------------------------------------------------------


def test_no_message_for_dry_skipped_running_or_interrupted_runs(make: Factories) -> None:
    runs = [
        make.run(NOW, stats={"date": DAY.isoformat()}, dry_run=True),
        make.run(NOW, status=RunStatus.FAILED, error="RuntimeError: x", dry_run=True),
        make.run(NOW, status=RunStatus.SKIPPED, stats={"reason": "paused"}),
        make.run(NOW, status=RunStatus.RUNNING),
        make.run(NOW, status=RunStatus.FAILED, error="interrupted (KeyboardInterrupt)"),
        make.run(NOW, kind=RunKind.REVIEW),
    ]

    assert [message_after_run(make.session, run, None) for run in runs] == [None] * 6


def test_failed_run_sends_the_error(make: Factories) -> None:
    run = make.run(NOW, kind=RunKind.REVIEW, status=RunStatus.FAILED, error="RuntimeError: x")

    message = message_after_run(make.session, run, None)

    assert message == run_failed_message(RunKind.REVIEW, run.id, "RuntimeError: x", None)


def test_digest_without_articles_sends_nothing(make: Factories) -> None:
    run = make.run(NOW, stats={"date": DAY.isoformat()})

    assert message_after_run(make.session, run, None) is None


def test_digest_sends_its_titles_in_order(make: Factories) -> None:
    make.article(digest_date=DAY, digest_position=2, title="Second", digest_title="Drugi")
    make.article(digest_date=DAY, digest_position=1, title="First", digest_title="Pierwszy")
    make.article(digest_date=DAY, digest_position=3, title="Third")
    run = make.run(NOW, stats={"date": DAY.isoformat()})

    message = message_after_run(make.session, run, "https://h/")

    assert message == digest_ready_message(["Pierwszy", "Drugi", "Third"], "https://h/")


def test_second_digest_of_the_day_sends_nothing(make: Factories) -> None:
    make.article(digest_date=DAY)
    make.run(NOW, stats={"date": DAY.isoformat()})
    forced = make.run(NOW + timedelta(hours=1), stats={"date": DAY.isoformat()})

    assert message_after_run(make.session, forced, None) is None


def test_real_digest_after_a_dry_one_still_notifies(make: Factories) -> None:
    make.article(digest_date=DAY)
    make.run(NOW, stats={"date": DAY.isoformat()}, dry_run=True)
    real = make.run(NOW + timedelta(hours=1), stats={"date": DAY.isoformat()})

    message = message_after_run(make.session, real, None)

    assert message is not None
    assert message.title == "brzask: today's 1 is ready"


def test_a_sent_notification_logs_no_url_even_at_debug(
    hook_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        sent = AppriseNotifier([hook_url]).send(Message("t", "b"))

    assert sent is True
    assert "secret-path-token" not in caplog.text


def test_a_failed_target_is_logged_by_position_and_service(hook_url: str) -> None:
    notifier = AppriseNotifier([hook_url, "json://127.0.0.1:9/secret-dead"])

    with capture_logs() as logs:
        sent = notifier.send(Message("t", "b"))

    assert sent is False
    assert logs == [
        {
            "event": "notification not sent",
            "failed": [{"entry": 2, "service": "JSON", "status": "failure"}],
            "log_level": "warning",
        }
    ]
