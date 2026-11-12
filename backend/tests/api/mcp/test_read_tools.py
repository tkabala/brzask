from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from brzask.db.models import RunKind, SourceStatus
from brzask.services.sources import mute_source
from tests.api.mcp.conftest import Connect, data, error_text
from tests.factories import TEST_MODEL, Factories, unit_vector

pytestmark = pytest.mark.anyio

DAY = date(2026, 11, 10)
SEEN = datetime(2026, 11, 10, 6, tzinfo=UTC)


@pytest.fixture(autouse=True)
def test_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL", TEST_MODEL)


async def test_get_digest_marks_article_text_as_external(
    connect: Connect, read_token: str, make: Factories
) -> None:
    blog = make.source("Blog")
    first = make.article(
        blog, digest_date=DAY, title="Original", digest_title="Translated", summary="S"
    )
    make.article(blog, digest_date=DAY, opened_at=SEEN)

    async with connect(read_token) as client:
        digest = data(await client.call_tool("get_digest", {"day": "2026-11-10"}))

    assert digest["date"] == "2026-11-10"
    assert digest["articles"][0]["id"] == first.id
    article = digest["articles"][0]
    assert "title" not in article and "summary" not in article
    assert article["external"] == {
        "title": "Translated",
        "original_title": "Original",
        "summary": "S",
        "why_it_matters": None,
        "source_name": "Blog",
    }
    assert digest["articles"][1]["opened_at"] is not None


async def test_list_digest_days(connect: Connect, read_token: str, make: Factories) -> None:
    make.article(digest_date=DAY, opened_at=SEEN)
    make.article(digest_date=date(2026, 11, 9))

    async with connect(read_token) as client:
        days = data(await client.call_tool("list_digest_days", {"limit": 5}))["result"]

    assert days == [
        {"date": "2026-11-10", "articles": 1, "opened": 1},
        {"date": "2026-11-09", "articles": 1, "opened": 0},
    ]


async def test_get_article_caps_its_text(
    connect: Connect, read_token: str, make: Factories
) -> None:
    article = make.article(extracted_text="word\t" * 1800 + "end", extracted_by="trafilatura")

    async with connect(read_token) as client:
        found = data(await client.call_tool("get_article", {"article_id": article.id}))

    assert found["extracted_by"] == "trafilatura"
    assert len(found["external"]["text"]) == 8000
    assert found["external"]["truncated"] is True


async def test_an_unknown_article_is_a_tool_error(connect: Connect, read_token: str) -> None:
    async with connect(read_token) as client:
        result = await client.call_tool("get_article", {"article_id": 999})

    assert "no article 999" in error_text(result)


async def test_explain_ranking(connect: Connect, read_token: str, make: Factories) -> None:
    run = make.run(
        SEEN,
        stats={"pool": {"candidates": 180}, "ranking": {"ranked": 180, "top": 15, "method": "llm"}},
    )
    article = make.article(digest_date=DAY, first_seen_at=SEEN, rank=3, why_it_matters="Because")

    async with connect(read_token) as client:
        ranking = data(await client.call_tool("explain_ranking", {"article_id": article.id}))

    assert (ranking["rank"], ranking["pool"], ranking["top"]) == (3, 180, 15)
    assert ranking["run_id"] == str(run.id)
    assert ranking["external"]["why_it_matters"] == "Because"


async def test_search_articles(
    connect: Connect, read_token: str, make: Factories, query_vectors: dict[str, list[float]]
) -> None:
    near = make.article(title="Postgres 18", embedding=unit_vector(1, 0.1))
    make.article(title="Rust", embedding=unit_vector(0, 1))
    query_vectors["postgres"] = unit_vector(1, 0)

    async with connect(read_token) as client:
        found = data(await client.call_tool("search_articles", {"query": "postgres", "limit": 1}))

    assert found["model"] == TEST_MODEL
    assert [hit["article"]["id"] for hit in found["items"]] == [near.id]
    assert found["items"][0]["article"]["external"]["title"] == "Postgres 18"


async def test_list_and_get_sources(
    connect: Connect, read_token: str, make: Factories, session: Session
) -> None:
    blog = make.source("Blog")
    make.source("Pending one", status=SourceStatus.PENDING)
    mute_source(session, str(blog.id), actor="test", reason="never opened")

    async with connect(read_token) as client:
        pending = data(await client.call_tool("list_sources", {"status": ["pending"]}))
        one = data(await client.call_tool("get_source", {"source": "Blog"}))

    assert [s["external"]["name"] for s in pending["sources"]] == ["Pending one"]
    assert (one["id"], one["status"]) == (blog.id, "muted")
    assert "note" not in one
    assert one["external"] == {"name": "Blog", "note": "never opened"}
    assert one["activity"] == {"articles": 0, "ranked": 0, "shown": 0, "opened": 0}


async def test_source_survival(connect: Connect, read_token: str, make: Factories) -> None:
    make.source("Blog")

    async with connect(read_token) as client:
        survival = data(await client.call_tool("source_survival", {}))

    assert survival["rows"][0]["origin"] == "manual"
    assert survival["rows"][0]["added"] == 1


async def test_open_stats(connect: Connect, read_token: str, make: Factories) -> None:
    blog = make.source("Blog")
    make.article(blog, digest_date=date.today(), topic="AI", opened_at=SEEN)

    async with connect(read_token) as client:
        stats = data(await client.call_tool("open_stats", {"days": 7}))

    assert (stats["shown"], stats["opened"]) == (1, 1)
    assert stats["by_topic"] == [{"key": "AI", "shown": 1, "opened": 1}]
    assert stats["external"]["by_source"] == [{"key": "Blog", "shown": 1, "opened": 1}]


async def test_open_stats_window_is_bounded(connect: Connect, read_token: str) -> None:
    async with connect(read_token) as client:
        result = await client.call_tool("open_stats", {"days": 365})

    assert "90" in error_text(result)


async def test_dedup_decisions_name_both_articles(
    connect: Connect, read_token: str, make: Factories
) -> None:
    make.article(link="https://a.example/1", title="Story at A")
    make.article(link="https://b.example/1", title="Story at B")
    drops = [
        {
            "link": "https://b.example/1",
            "reason": "same_day",
            "similarity": 0.83,
            "duplicate_of": "https://a.example/1",
            "same_event": 0.91,
        },
        {"link": "https://gone.example/", "reason": "cross_day", "similarity": 0.95},
    ]
    run = make.run(
        SEEN,
        stats={
            "date": "2026-11-10",
            "deduplication": {"same_day_method": "judge", "judged_pairs": 4, "drops": drops},
        },
    )

    async with connect(read_token) as client:
        by_day = data(await client.call_tool("dedup_decisions", {"day": "2026-11-10"}))
        latest = data(await client.call_tool("dedup_decisions", {}))
        missing = await client.call_tool("dedup_decisions", {"day": "2026-01-01"})

    assert by_day == latest
    assert by_day["run_id"] == str(run.id)
    assert (by_day["same_day_method"], by_day["judged_pairs"]) == ("judge", 4)
    judged, repeat = by_day["drops"]
    assert judged["same_event"] == 0.91
    assert judged["external"] == {"title": "Story at B", "kept_title": "Story at A"}
    assert repeat["external"] == {"title": None, "kept_title": None}
    assert "no finished digest run for 2026-01-01" in error_text(missing)


async def test_costs(connect: Connect, read_token: str, make: Factories) -> None:
    make.run(datetime.now(UTC), cost=0.0123, kind=RunKind.DIGEST)

    async with connect(read_token) as client:
        costs = data(await client.call_tool("costs", {}))

    assert costs["budget"]["daily_limit_usd"] is None
    assert costs["budget"]["spent_today_usd"] == pytest.approx(0.0123)
    assert costs["recent_runs"][0]["cost_usd"] == pytest.approx(0.0123)


async def test_runs_keep_their_stats_external(
    connect: Connect, read_token: str, make: Factories
) -> None:
    run = make.run(SEEN, stats={"reason": "paused"}, kind=RunKind.REVIEW, error=None)

    async with connect(read_token) as client:
        listed = data(await client.call_tool("list_runs", {"kind": "review"}))
        one = data(await client.call_tool("get_run", {"run_id": str(run.id)}))

    assert [r["id"] for r in listed["runs"]] == [str(run.id)]
    assert one["external"]["stats"] == {"reason": "paused"}
    assert "stats" not in one


async def test_interests(connect: Connect, read_token: str, make: Factories) -> None:
    make.interest("Postgres", keywords=["pgvector"], notes="releases only")

    async with connect(read_token) as client:
        found = data(await client.call_tool("list_interests", {}))

    assert found["interests"][0] | {"id": 0} == {
        "id": 0,
        "topic": "Postgres",
        "keywords": ["pgvector"],
        "notes": "releases only",
        "active": True,
    }


async def test_get_status(connect: Connect, read_token: str, make: Factories) -> None:
    make.run(SEEN, stats={"secret": "stays out"}, kind=RunKind.DIGEST)

    async with connect(read_token) as client:
        status = data(await client.call_tool("get_status", {}))

    assert status["last_runs"]["digest"]["status"] == "ok"
    assert "stats" not in status["last_runs"]["digest"]


async def test_list_changes(
    connect: Connect, read_token: str, make: Factories, session: Session
) -> None:
    blog = make.source("Blog")
    mute_source(session, str(blog.id), actor="test", reason="never opened")

    async with connect(read_token) as client:
        found = data(await client.call_tool("list_changes", {"entity": f"source:{blog.id}"}))
        bad = await client.call_tool("list_changes", {"entity": "source"})

    [change] = found["changes"]
    assert (change["action"], change["actor"], change["entity"]) == (
        "source.mute",
        "test",
        f"source:{blog.id}",
    )
    assert change["external"]["reason"] == "never opened"
    assert "source:12" in error_text(bad)


async def test_dedup_decisions_skip_dry_runs_unless_asked_for(
    connect: Connect, read_token: str, make: Factories
) -> None:
    dedup = {"same_day_method": "judge", "drops": []}
    real = make.run(SEEN, stats={"date": "2026-11-10", "deduplication": dedup})
    dry = make.run(
        datetime(2026, 11, 11, 20, tzinfo=UTC),
        stats={"date": "2026-11-10", "deduplication": dedup},
        dry_run=True,
    )

    async with connect(read_token) as client:
        latest = data(await client.call_tool("dedup_decisions", {}))
        by_day = data(await client.call_tool("dedup_decisions", {"day": "2026-11-10"}))
        by_id = data(await client.call_tool("dedup_decisions", {"run_id": str(dry.id)}))

    assert latest["run_id"] == by_day["run_id"] == str(real.id)
    assert by_id["run_id"] == str(dry.id)
