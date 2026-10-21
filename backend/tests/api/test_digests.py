import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from brzask.db.models import RunKind, RunStatus
from brzask.repositories import RunRepository
from tests.factories import Factories

DAY = date(2026, 10, 20)
RUN_AT = datetime(2026, 10, 20, 7, tzinfo=UTC)


def test_digest_of_a_day_in_order(client: TestClient, make: Factories) -> None:
    source = make.source("Phoronix")
    second = make.article(source, digest_date=DAY, digest_position=2, title="B")
    first = make.article(
        source,
        digest_date=DAY,
        digest_position=1,
        title="Original",
        digest_title="Translated",
        summary="What happened.",
        why_it_matters="Why you care.",
        topic="Linux",
    )
    make.article(source, digest_date=date(2026, 10, 19))

    body = client.get(f"/api/v1/digests/{DAY}").json()

    assert body["date"] == "2026-10-20"
    assert [a["id"] for a in body["articles"]] == [first.id, second.id]
    shown = body["articles"][0]
    assert shown["title"] == "Translated"
    assert shown["original_title"] == "Original"
    assert shown["source"] == {"id": source.id, "name": "Phoronix"}
    assert (shown["summary"], shown["why_it_matters"], shown["topic"]) == (
        "What happened.",
        "Why you care.",
        "Linux",
    )
    assert shown["position"] == 1
    assert shown["state"] == "shown"


def test_day_without_a_digest_is_empty(client: TestClient) -> None:
    assert client.get("/api/v1/digests/2020-01-01").json() == {
        "date": "2020-01-01",
        "articles": [],
    }


@pytest.mark.parametrize("day", ["0", "20261020", "2026-02-30", "today2"])
def test_day_must_be_an_iso_date(client: TestClient, day: str) -> None:
    assert client.get(f"/api/v1/digests/{day}").status_code == 422


def test_today_uses_the_configured_time_zone(
    client: TestClient, make: Factories, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")  # UTC+14: often a day ahead of UTC
    from zoneinfo import ZoneInfo

    today = datetime.now(UTC).astimezone(ZoneInfo("Pacific/Kiritimati")).date()
    article = make.article(digest_date=today)

    body = client.get("/api/v1/digests/today").json()

    assert body["date"] == today.isoformat()
    assert [a["id"] for a in body["articles"]] == [article.id]


def test_archive_lists_days_newest_first_by_pages(client: TestClient, make: Factories) -> None:
    for day in (18, 19, 20):
        make.article(digest_date=date(2026, 10, day))
    make.article(digest_date=date(2026, 10, 20), opened_at=RUN_AT)

    first = client.get("/api/v1/digests", params={"limit": "2"}).json()
    rest = client.get(
        "/api/v1/digests", params={"limit": "2", "cursor": first["next_cursor"]}
    ).json()

    assert first["items"] == [
        {"date": "2026-10-20", "articles": 2, "opened": 1},
        {"date": "2026-10-19", "articles": 1, "opened": 0},
    ]
    assert rest == {
        "items": [{"date": "2026-10-18", "articles": 1, "opened": 0}],
        "next_cursor": None,
    }


def test_article(client: TestClient, make: Factories) -> None:
    article = make.article(title="Plain")

    body = client.get(f"/api/v1/articles/{article.id}").json()

    assert (body["title"], body["state"], body["digest_date"]) == ("Plain", "seen", None)


def test_unknown_article(client: TestClient) -> None:
    assert client.get("/api/v1/articles/999999").status_code == 404
    assert client.get("/api/v1/articles/99999999999999999999").status_code == 422


def test_ranking_explains_from_the_run(
    client: TestClient, make: Factories, session: Session
) -> None:
    runs = RunRepository(session)
    run = runs.start(uuid.uuid4(), RunKind.DIGEST, RUN_AT)
    runs.finish(
        run,
        RunStatus.OK,
        RUN_AT,
        stats={
            "pool": {"candidates": 212},
            "ranking": {"method": "llm", "ranked": 180, "top": 15},
            "deduplication": {"survivors": 12, "same_day_method": "judge"},
        },
    )
    article = make.article(
        digest_date=DAY,
        digest_position=3,
        first_seen_at=RUN_AT,
        rank=5,
        topic="Postgres",
        why_it_matters="A release you run.",
    )

    body = client.get(f"/api/v1/articles/{article.id}/ranking").json()

    assert body == {
        "article_id": article.id,
        "position": 3,
        "topic": "Postgres",
        "why_it_matters": "A release you run.",
        "rank": 5,
        "pool": 212,
        "ranked": 180,
        "top": 15,
        "ranking_method": "llm",
        "deduplicated_to": 12,
        "deduplication_method": "judge",
        "run_id": str(run.id),
    }


def test_ranking_without_a_run_has_only_the_article(client: TestClient, make: Factories) -> None:
    article = make.article(rank=40)

    body = client.get(f"/api/v1/articles/{article.id}/ranking").json()

    assert body["rank"] == 40
    assert body["run_id"] is None
    assert body["pool"] is None
