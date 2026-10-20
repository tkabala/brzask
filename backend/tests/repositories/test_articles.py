import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from brzask.db.models import ArticleState, Run, RunKind
from brzask.repositories import ArticleRepository, EmbeddingRepository
from brzask.repositories.articles import DigestEntry, DigestRun, Extraction, NewArticle
from tests.factories import TEST_MODEL, Factories, unit_vector

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)
TODAY = date(2026, 10, 18)


def entry(article_id: int, position: int) -> DigestEntry:
    return DigestEntry(
        article_id=article_id,
        position=position,
        title=f"Title {position}",
        summary="Summary",
        why_it_matters="Why",
        topic="Topic",
    )


# --- Candidates ----------------------------------------------------------------


def test_add_new_returns_ids_of_new_and_known_links(session: Session, make: Factories) -> None:
    source = make.source()
    known = make.article(source, link="https://a.example/1", title="Kept title")
    articles = ArticleRepository(session)

    ids = articles.add_new(
        [
            NewArticle("https://a.example/1", "Changed title", source.id),
            NewArticle("https://a.example/2", "New", source.id, snippet="s", published_at=NOW),
        ]
    )

    assert ids["https://a.example/1"] == known.id
    new = articles.get(ids["https://a.example/2"])
    assert new is not None
    assert (new.title, new.snippet, new.published_at, new.state) == ("New", "s", NOW, "seen")
    session.refresh(known)
    assert known.title == "Kept title"


def test_add_new_with_nothing_does_nothing(session: Session) -> None:
    assert ArticleRepository(session).add_new([]) == {}


def test_add_new_stores_more_rows_than_one_statement_takes(session: Session) -> None:
    # 14,000 rows x 5 columns is more than the 65,535 parameters of one statement.
    links = [f"https://bulk.example/{n}" for n in range(14_000)]

    ids = ArticleRepository(session).add_new([NewArticle(link, "Title", None) for link in links])

    assert len(ids) == len(links)
    assert set(ids) == set(links)


def test_shown_links_within_the_window(session: Session, make: Factories) -> None:
    make.article(link="https://a.example/recent", digest_date=TODAY, shown_at=NOW)
    make.article(
        link="https://a.example/old",
        digest_date=date(2026, 7, 1),
        shown_at=NOW - timedelta(days=90),
    )
    make.article(link="https://a.example/seen")

    links = ArticleRepository(session).shown_links(since=NOW - timedelta(days=60))

    assert links == {"https://a.example/recent"}
    assert ArticleRepository(session).shown_links() == {
        "https://a.example/recent",
        "https://a.example/old",
    }


def test_carry_over_is_unshown_articles_seen_since(session: Session, make: Factories) -> None:
    older = make.article(first_seen_at=NOW - timedelta(days=5))
    newer = make.article(first_seen_at=NOW - timedelta(days=1))
    make.article(first_seen_at=NOW - timedelta(days=8))  # too old
    make.article(first_seen_at=NOW - timedelta(days=1), digest_date=TODAY)  # already shown

    carried = ArticleRepository(session).carry_over(since=NOW - timedelta(days=7))

    assert list(carried) == [older, newer]


def test_shown_embeddings_compare_only_the_same_model(session: Session, make: Factories) -> None:
    make.article(digest_date=TODAY, shown_at=NOW, embedding=unit_vector(1, 0))
    make.article(
        digest_date=TODAY, shown_at=NOW, embedding=unit_vector(0, 1), embedding_model="other"
    )
    make.article(embedding=unit_vector(1, 1))  # not shown
    make.article(
        digest_date=TODAY - timedelta(days=9),
        shown_at=NOW - timedelta(days=9),
        embedding=unit_vector(1, 1),
    )

    vectors = ArticleRepository(session).shown_embeddings(NOW - timedelta(days=7), TEST_MODEL)

    assert len(vectors) == 1
    assert vectors[0] == pytest.approx(unit_vector(1, 0))


def test_recent_opens_newest_first_with_source_names(session: Session, make: Factories) -> None:
    source = make.source("Lobsters")
    make.article(source, title="First", opened_at=NOW - timedelta(days=2), topic="Rust")
    make.article(None, title="Second", opened_at=NOW - timedelta(days=1))
    make.article(source, title="Third", opened_at=NOW)
    make.article(source, title="Too old", opened_at=NOW - timedelta(days=100))
    make.article(source, title="Never opened")

    opens = ArticleRepository(session).recent_opens(since=NOW - timedelta(days=90), limit=2)

    assert [(o.title, o.source_name) for o in opens] == [("Third", "Lobsters"), ("Second", None)]
    everything = ArticleRepository(session).recent_opens(since=NOW - timedelta(days=90), limit=10)
    assert everything[-1].topic == "Rust"


def test_history_reads_can_stop_at_a_moment(session: Session, make: Factories) -> None:
    make.article(title="Before", opened_at=NOW - timedelta(hours=1))
    make.article(title="After", opened_at=NOW + timedelta(hours=1))
    make.article(digest_date=TODAY, shown_at=NOW - timedelta(days=1), embedding=unit_vector(0, 1))
    make.article(digest_date=TODAY, shown_at=NOW, embedding=unit_vector(1, 1))
    articles = ArticleRepository(session)

    opens = articles.recent_opens(NOW - timedelta(days=90), 10, before=NOW)
    vectors = articles.shown_embeddings(NOW - timedelta(days=7), TEST_MODEL, before=NOW)

    assert [o.title for o in opens] == ["Before"]
    assert vectors == [pytest.approx(unit_vector(0, 1))]


def test_seen_between_is_what_a_past_run_could_choose_from(
    session: Session, make: Factories
) -> None:
    source = make.source("Lobsters")
    run_at, run_end = NOW, NOW + timedelta(minutes=5)
    since = NOW - timedelta(days=7)
    fresh = make.article(source, title="Fresh", first_seen_at=NOW - timedelta(hours=1))
    # Stored by the run itself, after it started, and picked by it.
    stored_by_run = make.article(
        source,
        title="Stored by the run",
        first_seen_at=NOW + timedelta(minutes=1),
        shown_at=run_at,
        digest_date=TODAY,
    )
    picked = make.article(  # shown by this very run
        source,
        title="Picked",
        first_seen_at=NOW - timedelta(days=1),
        shown_at=run_at,
        digest_date=TODAY,
    )
    later = make.article(  # shown by a later run: still a candidate then
        source,
        title="Later",
        first_seen_at=NOW - timedelta(days=2),
        shown_at=NOW + timedelta(days=1),
        digest_date=TODAY + timedelta(days=1),
    )
    make.article(  # shown before the run
        source,
        first_seen_at=NOW - timedelta(days=3),
        shown_at=NOW - timedelta(days=1),
        digest_date=TODAY - timedelta(days=1),
    )
    make.article(source, first_seen_at=NOW - timedelta(days=8))  # before the window
    make.article(source, first_seen_at=NOW + timedelta(minutes=10))  # after the run
    make.article(None, first_seen_at=NOW - timedelta(hours=2))  # no source

    stored = ArticleRepository(session).seen_between(since, run_at, run_end)

    assert stored == [later, picked, fresh, stored_by_run]
    assert stored[0].source is not None and stored[0].source.name == "Lobsters"


def test_digest_runs_by_day_with_the_first_run(session: Session, make: Factories) -> None:
    yesterday = NOW - timedelta(days=1)
    make.article(digest_date=TODAY - timedelta(days=3), shown_at=NOW - timedelta(days=3))
    make.article(
        digest_date=TODAY - timedelta(days=1),
        shown_at=yesterday,
        first_seen_at=yesterday + timedelta(minutes=1),
    )
    make.article(  # appended by a forced run later that day
        digest_date=TODAY - timedelta(days=1),
        shown_at=NOW - timedelta(hours=20),
        first_seen_at=yesterday - timedelta(hours=1),
    )
    make.article(digest_date=TODAY, shown_at=NOW, first_seen_at=NOW - timedelta(days=1))
    session.add(
        Run(
            id=uuid.uuid4(),
            kind=RunKind.DIGEST,
            started_at=NOW,
            finished_at=NOW + timedelta(minutes=5),
        )
    )
    session.flush()

    runs = ArticleRepository(session).digest_runs(since=TODAY - timedelta(days=1))

    assert runs == [
        # No run row: the day's latest first sighting bounds the run.
        DigestRun(TODAY - timedelta(days=1), yesterday, yesterday + timedelta(minutes=1)),
        DigestRun(TODAY, NOW, NOW + timedelta(minutes=5)),
    ]


def test_opened_since(session: Session, make: Factories) -> None:
    opened = make.article(opened_at=NOW - timedelta(days=3))
    make.article(opened_at=NOW - timedelta(days=31))
    make.article()

    assert list(ArticleRepository(session).opened_since(NOW - timedelta(days=30))) == [opened]


# --- Pipeline results ----------------------------------------------------------


def test_set_ranks_updates_loaded_articles(session: Session, make: Factories) -> None:
    first, second = make.article(), make.article()

    ArticleRepository(session).set_ranks({first.id: 2, second.id: 1})

    assert (first.rank, second.rank) == (2, 1)


def test_save_extractions_stores_text_and_vector(session: Session, make: Factories) -> None:
    article = make.article()
    vector = unit_vector(3, 4)

    ArticleRepository(session).save_extractions(
        [Extraction(article.id, "Full text", "trafilatura", vector, TEST_MODEL)]
    )

    assert (article.extracted_text, article.extracted_by) == ("Full text", "trafilatura")
    stored = EmbeddingRepository(session).of_articles([article.id], TEST_MODEL)
    assert stored[article.id] == pytest.approx(vector)


def test_save_extraction_without_text_or_vector(session: Session, make: Factories) -> None:
    article = make.article()

    ArticleRepository(session).save_extractions([Extraction(article.id, None, None, None, None)])

    assert EmbeddingRepository(session).counts_by_model() == {}
    assert article.extracted_text is None


def test_last_digest_position(session: Session, make: Factories) -> None:
    articles = ArticleRepository(session)
    assert articles.last_digest_position(TODAY) is None

    make.article(digest_date=TODAY, digest_position=1)
    make.article(digest_date=TODAY, digest_position=7)
    make.article(digest_date=TODAY - timedelta(days=1), digest_position=9)

    assert articles.last_digest_position(TODAY) == 7


def test_mark_shown_writes_the_digest(session: Session, make: Factories) -> None:
    first, second = make.article(), make.article()
    articles = ArticleRepository(session)

    articles.mark_shown(TODAY, [entry(second.id, 1), entry(first.id, 2)], shown_at=NOW)

    assert list(articles.digest(TODAY)) == [second, first]
    assert second.state is ArticleState.SHOWN
    assert (second.shown_at, second.digest_title, second.topic) == (NOW, "Title 1", "Topic")


# --- Reading digests -----------------------------------------------------------


def test_digest_loads_sources(session: Session, make: Factories) -> None:
    source = make.source("Source name")
    make.article(source, digest_date=TODAY)
    session.expunge_all()

    [article] = ArticleRepository(session).digest(TODAY)
    session.close()

    assert article.source is not None
    assert article.source.name == "Source name"


def test_latest_digest_date(session: Session, make: Factories) -> None:
    articles = ArticleRepository(session)
    assert articles.latest_digest_date() is None

    make.article(digest_date=TODAY - timedelta(days=2))
    make.article(digest_date=TODAY)

    assert articles.latest_digest_date() == TODAY


def test_digest_days_count_articles_and_opens(session: Session, make: Factories) -> None:
    for days_ago in range(3):
        day = TODAY - timedelta(days=days_ago)
        make.article(digest_date=day, opened_at=NOW)
        make.article(digest_date=day)
    make.article()
    articles = ArticleRepository(session)

    page = articles.digest_days(limit=2)
    rest = articles.digest_days(limit=2, before=page[-1].day)

    assert [(d.day, d.articles, d.opened) for d in page] == [
        (TODAY, 2, 1),
        (TODAY - timedelta(days=1), 2, 1),
    ]
    assert [d.day for d in rest] == [TODAY - timedelta(days=2)]


def test_record_open_keeps_the_first_open(session: Session, make: Factories) -> None:
    article = make.article(link="https://a.example/x")
    articles = ArticleRepository(session)

    assert articles.record_open(article.id, NOW) == "https://a.example/x"
    assert articles.record_open(article.id, NOW + timedelta(hours=1)) == "https://a.example/x"

    assert article.opened_at == NOW


def test_record_open_of_an_unknown_article(session: Session) -> None:
    assert ArticleRepository(session).record_open(123456, NOW) is None


# --- Search --------------------------------------------------------------------


def test_search_similar_orders_by_cosine_similarity(session: Session, make: Factories) -> None:
    exact = make.article(embedding=unit_vector(1, 0))
    close = make.article(embedding=unit_vector(1, 1))
    make.article(embedding=unit_vector(0, 1))
    make.article(embedding=unit_vector(1, 0), embedding_model="other")
    make.article()

    results = ArticleRepository(session).search_similar(unit_vector(1, 0), TEST_MODEL, limit=2)

    assert [r.article for r in results] == [exact, close]
    assert results[0].similarity == pytest.approx(1.0)
    assert results[1].similarity == pytest.approx(0.7071, abs=1e-4)


def test_search_text_matches_titles_and_summaries(session: Session, make: Factories) -> None:
    by_title = make.article(title="Postgres 18 released", first_seen_at=NOW - timedelta(days=2))
    by_summary = make.article(
        title="Release notes", summary="What is new in POSTGRES", first_seen_at=NOW
    )
    make.article(title="Unrelated")
    articles = ArticleRepository(session)

    assert list(articles.search_text("postgres", limit=10)) == [by_summary, by_title]
    assert list(articles.search_text("100%", limit=10)) == []
    assert list(articles.search_text("_", limit=10)) == []


def test_counts(session: Session, make: Factories) -> None:
    make.article()
    make.article(digest_date=TODAY)
    make.article(digest_date=TODAY, opened_at=NOW)

    counts = ArticleRepository(session).counts()

    assert (counts.total, counts.shown, counts.opened) == (3, 2, 1)
