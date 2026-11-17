"""Briefs: parsing the model's answer, clipping the input, and the stage on Postgres."""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from brzask import prompts
from brzask.clients.llm import Completion, InvalidJSONError
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.db.models import ArticleBrief, ArticleContent, BriefBasis, ContentKind
from brzask.services import briefs
from brzask.services.briefs import (
    Brief,
    BriefError,
    Chapter,
    NothingToBriefError,
    basis,
    clip,
    last_marker,
    parse_brief,
    write_brief,
    write_missing,
)
from tests.factories import Factories
from tests.services.digest.fakes import NOW, context

DAY = date(2026, 10, 18)
ENGLISH = prompts.language("en")

VALID: dict[str, Any] = {
    "gist": "Postgres 18 reads data asynchronously. Scans get faster on cloud disks.",
    "points": [
        "io_method = worker is the default",
        "Sequential scans 2-3x faster on EBS",
        "io_uring needs Linux 5.1",
        "Bitmap heap scans use it too",
    ],
    "caveats": ["Benchmarks by the vendor"],
    "chapters": [],
}


def answer(**fields: Any) -> dict[str, Any]:
    return {**VALID, **fields}


# --- parse_brief ------------------------------------------------------------------


def test_a_valid_text_article() -> None:
    brief = parse_brief(VALID, ContentKind.PAGE, None)

    assert brief == Brief(
        gist=VALID["gist"], points=VALID["points"], caveats=VALID["caveats"], chapters=[]
    )


def test_two_points_is_an_error() -> None:
    with pytest.raises(BriefError):
        parse_brief(answer(points=["one", "two"]), ContentKind.PAGE, None)


@pytest.mark.parametrize("points", [[], ["", "  "]])
def test_no_points_means_nothing_to_brief(points: list[str]) -> None:
    with pytest.raises(NothingToBriefError):
        parse_brief(
            answer(points=points, gist="Only GitHub session notices."), ContentKind.PAGE, None
        )


def test_points_that_are_not_text_are_an_error_not_an_empty_brief() -> None:
    # Asked again, rather than taken for a page with nothing to brief.
    points = [{"claim": "io_method = worker is the default"}, {"claim": "2-3x faster"}]

    with pytest.raises(BriefError):
        parse_brief(answer(points=points), ContentKind.PAGE, None)


def test_an_answer_without_a_points_list_is_an_error_not_an_empty_brief() -> None:
    # E.g. a provider echoing the request's response format instead of an answer.
    with pytest.raises(BriefError):
        parse_brief({"type": "json_object"}, ContentKind.PAGE, None)


def test_twenty_points_are_cut_to_seven() -> None:
    brief = parse_brief(answer(points=[f"point {n}" for n in range(20)]), ContentKind.PAGE, None)

    assert brief.points == [f"point {n}" for n in range(7)]


def test_whitespace_points_are_dropped() -> None:
    points = ["  first  ", " ", "", "second", "\n", "third", 42]

    brief = parse_brief(answer(points=points), ContentKind.PAGE, None)

    assert brief.points == ["first", "second", "third"]


def test_empty_points_do_not_count_toward_the_minimum() -> None:
    with pytest.raises(BriefError):
        parse_brief(answer(points=["one", " ", "two", ""]), ContentKind.PAGE, None)


def test_caveats_are_cut_to_three_and_may_be_missing() -> None:
    many = parse_brief(answer(caveats=["a", " ", "b", "c", "d"]), ContentKind.PAGE, None)
    without = parse_brief(
        {k: v for k, v in VALID.items() if k != "caveats"}, ContentKind.PAGE, None
    )

    assert many.caveats == ["a", "b", "c"]
    assert without.caveats == []


def test_chapters_of_another_type_are_ignored_for_a_page() -> None:
    brief = parse_brief(answer(chapters="none"), ContentKind.PAGE, None)

    assert brief.chapters == []


def test_chapters_are_dropped_for_a_page() -> None:
    brief = parse_brief(answer(chapters=[{"start": 0, "title": "Intro"}]), ContentKind.PAGE, 600)

    assert brief.chapters == []


def test_chapters_are_kept_for_a_transcript() -> None:
    chapters = [{"start": 0, "title": " Intro "}, {"start": 120.0, "title": "Setup"}]

    brief = parse_brief(answer(chapters=chapters), ContentKind.TRANSCRIPT, 600)

    assert brief.chapters == [Chapter(0, "Intro"), Chapter(120, "Setup")]


def test_chapter_past_the_end_is_dropped() -> None:
    chapters = [{"start": 30, "title": "Inside"}, {"start": 700, "title": "Past the end"}]

    brief = parse_brief(answer(chapters=chapters), ContentKind.TRANSCRIPT, 600)

    assert brief.chapters == [Chapter(30, "Inside")]


def test_chapters_are_sorted_and_unique() -> None:
    chapters = [
        {"start": 300, "title": "Third"},
        {"start": 10, "title": "First"},
        {"start": 300, "title": "Third again"},
        {"start": 100, "title": "Second"},
    ]

    brief = parse_brief(answer(chapters=chapters), ContentKind.TRANSCRIPT, 600)

    assert brief.chapters == [Chapter(10, "First"), Chapter(100, "Second"), Chapter(300, "Third")]


def test_more_than_eight_chapters_are_cut_to_eight() -> None:
    chapters = [{"start": n * 10, "title": f"Part {n}"} for n in range(12)]

    brief = parse_brief(answer(chapters=chapters), ContentKind.TRANSCRIPT, 600)

    assert [c.start for c in brief.chapters] == [n * 10 for n in range(8)]


def test_malformed_chapters_are_dropped() -> None:
    chapters = [
        {"start": -5, "title": "Before the start"},
        {"start": True, "title": "A bool"},
        {"start": "60", "title": "A string"},
        {"start": 12.5, "title": "A fraction"},
        {"start": 90, "title": "  "},
        {"start": 90},
        "not an object",
        {"start": 200, "title": "Kept"},
    ]

    brief = parse_brief(answer(chapters=chapters), ContentKind.TRANSCRIPT, 600)

    assert brief.chapters == [Chapter(200, "Kept")]


def test_a_transcript_without_markers_keeps_no_chapters() -> None:
    brief = parse_brief(
        answer(chapters=[{"start": 0, "title": "Intro"}]), ContentKind.TRANSCRIPT, None
    )

    assert brief.chapters == []


@pytest.mark.parametrize("gist", [None, "", "   ", 7])
def test_missing_gist_is_an_error(gist: Any) -> None:
    with pytest.raises(BriefError):
        parse_brief(answer(gist=gist), ContentKind.PAGE, None)


@pytest.mark.parametrize("value", [[VALID], "brief", None, 3])
def test_non_object_answer_is_an_error(value: Any) -> None:
    with pytest.raises(BriefError):
        parse_brief(value, ContentKind.PAGE, None)


@pytest.mark.parametrize("field", ["points", "caveats", "chapters"])
def test_a_list_field_of_another_type_is_an_error(field: str) -> None:
    with pytest.raises(BriefError):
        parse_brief(answer(**{field: "one, two, three"}), ContentKind.TRANSCRIPT, 600)


# --- clip, last_marker, basis -----------------------------------------------------


def test_clip_leaves_a_text_under_the_limit() -> None:
    assert clip("a\n\nb", limit=10) == ("a\n\nb", False)
    assert clip("x" * 10, limit=10) == ("x" * 10, False)


def test_clip_cuts_at_the_last_paragraph_before_the_limit() -> None:
    text = "first paragraph\n\nsecond paragraph\n\nthird paragraph"

    clipped, cut = clip(text, limit=40)

    assert (clipped, cut) == ("first paragraph\n\nsecond paragraph", True)


def test_clip_without_blank_lines_cuts_at_the_last_line_break() -> None:
    text = "first line here\nsecond line here\nthird line here"

    clipped, cut = clip(text, limit=40)

    assert (clipped, cut) == ("first line here\nsecond line here", True)


def test_clip_of_one_line_cuts_after_the_last_sentence() -> None:
    text = "First sentence here. Second sentence here. Third sentence here."

    clipped, cut = clip(text, limit=50)

    assert (clipped, cut) == ("First sentence here. Second sentence here.", True)


def test_clip_cuts_one_giant_paragraph_at_the_limit() -> None:
    clipped, cut = clip("x" * 100, limit=40)

    assert (clipped, cut) == ("x" * 40, True)


def test_the_input_cap() -> None:
    assert briefs.BRIEF_INPUT_CHARS == 120_000


def test_last_marker_reads_both_forms() -> None:
    assert last_marker("[00:31] a\n\n[1:00:05] b") == 3605
    assert last_marker("[00:00] a\n\n[12:31] b") == 751


def test_last_marker_without_markers() -> None:
    assert last_marker("No markers, only [a bracket] in text.") is None


@pytest.mark.parametrize(
    ("kind", "clipped", "expected"),
    [
        (ContentKind.PAGE, False, BriefBasis.FULL_TEXT),
        (ContentKind.TRANSCRIPT, False, BriefBasis.TRANSCRIPT),
        (ContentKind.DESCRIPTION, False, BriefBasis.DESCRIPTION),
        (ContentKind.PAGE, True, BriefBasis.PARTIAL),
        (ContentKind.TRANSCRIPT, True, BriefBasis.PARTIAL),
    ],
)
def test_basis(kind: ContentKind, clipped: bool, expected: BriefBasis) -> None:
    assert basis(kind, clipped) is expected


# --- write_brief ------------------------------------------------------------------


class FakeLLM:
    """Answers each brief prompt with `answers(prompt, call number)`; may raise."""

    def __init__(self, answers: Callable[[str, int], Any]) -> None:
        self.answers = answers
        self.prompts: list[str] = []
        self.purposes: list[str] = []

    def complete_json(
        self, prompt: str, *, purpose: str, meter: UsageMeter | None = None
    ) -> tuple[Any, Completion]:
        self.prompts.append(prompt)
        self.purposes.append(purpose)
        usage = CallUsage("test/brief-model", purpose, 100, 10, 0.001, 1)
        if meter is not None:
            meter.add(usage)
        value = self.answers(prompt, len(self.prompts))
        if isinstance(value, Exception):
            raise value
        return value, Completion("{}", usage)


def page(text: str = "Long text. " * 50, kind: ContentKind = ContentKind.PAGE) -> ArticleContent:
    return ArticleContent(article_id=1, text=text, kind=kind, extracted_by="trafilatura")


def test_write_brief_retries_an_invalid_answer_once(make: Factories) -> None:
    article = make.article(title="Async I/O")
    llm = FakeLLM(lambda _, n: {"gist": ""} if n == 1 else VALID)
    meter = UsageMeter()

    brief, written_on, model = write_brief(llm, page(), article, [], ENGLISH, meter)

    assert brief.gist == VALID["gist"]
    assert written_on is BriefBasis.FULL_TEXT
    assert model == "test/brief-model"
    assert llm.purposes == ["brief", "brief"]
    assert len(meter.calls) == 2


def test_write_brief_retries_an_answer_that_is_not_json(make: Factories) -> None:
    article = make.article()
    llm = FakeLLM(lambda _, n: InvalidJSONError("Sure!") if n == 1 else VALID)

    brief, _, _ = write_brief(llm, page(), article, [], ENGLISH, None)

    assert brief.points == VALID["points"]
    assert len(llm.prompts) == 2


def test_write_brief_gives_up_after_two_invalid_answers(make: Factories) -> None:
    article = make.article()
    llm = FakeLLM(lambda _, __: answer(points=["one", "two"]))

    with pytest.raises(BriefError):
        write_brief(llm, page(), article, [], ENGLISH, None)
    assert len(llm.prompts) == 2


def test_write_brief_takes_no_points_as_nothing_to_brief_without_asking_again(
    make: Factories,
) -> None:
    article = make.article()
    llm = FakeLLM(lambda _, __: answer(points=[]))

    with pytest.raises(NothingToBriefError):
        write_brief(llm, page(), article, [], ENGLISH, None)
    assert len(llm.prompts) == 1


def test_write_brief_clips_a_long_text_and_marks_it_partial(
    make: Factories, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(briefs, "BRIEF_INPUT_CHARS", 60)
    article = make.article()
    text = "[00:00] intro words here\n\n[00:40] middle words here\n\n[01:30] end words here"
    chapters = [{"start": 0, "title": "Intro"}, {"start": 40, "title": "Middle"}]
    chapters.append({"start": 90, "title": "End, cut off"})
    llm = FakeLLM(lambda _, __: answer(chapters=chapters))

    brief, written_on, _ = write_brief(
        llm, page(text, ContentKind.TRANSCRIPT), article, [], ENGLISH, None
    )

    assert written_on is BriefBasis.PARTIAL
    assert "end words here" not in llm.prompts[0]
    assert "middle words here" in llm.prompts[0]
    # Chapters are checked against what the model saw.
    assert brief.chapters == [Chapter(0, "Intro"), Chapter(40, "Middle")]


def test_write_brief_prompt_holds_the_article(make: Factories) -> None:
    source = make.source(name="PG Weekly")
    article = make.article(source, title="Async I/O")
    interests = [{"topic": "Postgres", "keywords": ["pgvector"], "notes": ""}]
    llm = FakeLLM(lambda _, __: VALID)

    write_brief(llm, page("Body of the article."), article, interests, prompts.language("pl"), None)

    prompt = llm.prompts[0]
    assert "<untrusted>Async I/O</untrusted>" in prompt
    assert "<untrusted>PG Weekly</untrusted>" in prompt
    assert "<untrusted>\nBody of the article.\n</untrusted>" in prompt
    assert "- Postgres: pgvector" in prompt
    assert "Polish" in prompt


# --- write_missing (Postgres) -----------------------------------------------------


def digest_article(make: Factories, title: str, day: date, text: str = "Body. " * 100) -> int:
    article = make.article(title=title, digest_date=day)
    make.session.add(
        ArticleContent(article_id=article.id, text=text, kind=ContentKind.PAGE, extracted_by="t")
    )
    make.session.flush()
    return article.id


def briefs_by_article(session: Session) -> dict[int, ArticleBrief]:
    session.expire_all()
    return {brief.article_id: brief for brief in session.scalars(select(ArticleBrief))}


def failing_on(title: str) -> Callable[[str, int], Any]:
    return lambda prompt, _: {"gist": ""} if f"<untrusted>{title}</untrusted>" in prompt else VALID


def test_write_missing_writes_a_brief_per_digest_article(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    ids = [digest_article(make, title, DAY) for title in ("First", "Second", "Third")]
    run = context(sessions)
    llm = FakeLLM(failing_on("Second"))

    write_missing(run, llm, ENGLISH, DAY)

    stored = briefs_by_article(session)
    assert set(stored) == {ids[0], ids[2]}
    assert run.stats["briefs"] == {"written": 2, "failed": 1, "skipped": 0, "empty": 0}
    assert "briefs" in run.timings
    first = stored[ids[0]]
    assert (first.gist, first.points, first.caveats) == (
        VALID["gist"],
        VALID["points"],
        VALID["caveats"],
    )
    assert (first.chapters, first.basis, first.model) == (
        [],
        BriefBasis.FULL_TEXT,
        "test/brief-model",
    )
    assert len(run.usage.calls) == 1 + 2 + 1  # the second one retried once

    # A run later fills in the missing one and leaves the others as they are.
    created = {article_id: brief.created_at for article_id, brief in stored.items()}
    again = context(sessions)
    second_llm = FakeLLM(lambda _, __: answer(gist="Another gist."))
    write_missing(again, second_llm, ENGLISH, DAY)

    stored = briefs_by_article(session)
    assert set(stored) == set(ids)
    assert again.stats["briefs"] == {"written": 1, "failed": 0, "skipped": 0, "empty": 0}
    assert len(second_llm.prompts) == 1
    assert stored[ids[1]].gist == "Another gist."
    assert {i: stored[i].created_at for i in (ids[0], ids[2])} == created
    assert stored[ids[0]].gist == VALID["gist"]


def test_write_missing_retries_yesterday_but_not_older_days(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    yesterday = digest_article(make, "Yesterday", DAY - timedelta(days=1))
    digest_article(make, "Two days ago", DAY - timedelta(days=2))
    digest_article(make, "Three days ago", DAY - timedelta(days=3))
    llm = FakeLLM(lambda _, __: VALID)

    write_missing(context(sessions), llm, ENGLISH, DAY)

    assert set(briefs_by_article(session)) == {yesterday}
    assert len(llm.prompts) == 1


def test_write_missing_skips_a_text_too_short_to_brief(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    digest_article(make, "Teaser", DAY, text="x" * 150)
    run = context(sessions)
    llm = FakeLLM(lambda _, __: VALID)

    write_missing(run, llm, ENGLISH, DAY)

    assert llm.prompts == []
    assert briefs_by_article(session) == {}
    assert run.stats["briefs"] == {"written": 0, "failed": 0, "skipped": 1, "empty": 0}


def test_write_missing_stores_nothing_for_a_text_with_nothing_to_brief(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    kept = digest_article(make, "Release notes", DAY)
    digest_article(make, "Session notice", DAY)
    run = context(sessions)
    llm = FakeLLM(
        lambda prompt, _: (
            answer(points=[]) if "<untrusted>Session notice</untrusted>" in prompt else VALID
        )
    )

    write_missing(run, llm, ENGLISH, DAY)

    assert set(briefs_by_article(session)) == {kept}
    assert run.stats["briefs"] == {"written": 1, "failed": 0, "skipped": 0, "empty": 1}
    assert len(llm.prompts) == 2


def test_write_missing_leaves_later_days_alone(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    today = digest_article(make, "Today", DAY)
    digest_article(make, "Tomorrow", DAY + timedelta(days=1))
    llm = FakeLLM(lambda _, __: VALID)

    write_missing(context(sessions), llm, ENGLISH, DAY)

    assert set(briefs_by_article(session)) == {today}


def test_write_missing_counts_a_raising_model_as_failed(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    digest_article(make, "First", DAY)
    digest_article(make, "Second", DAY)
    run = context(sessions)
    llm = FakeLLM(lambda _, __: RuntimeError("provider down"))

    write_missing(run, llm, ENGLISH, DAY)

    assert briefs_by_article(session) == {}
    assert run.stats["briefs"] == {"written": 0, "failed": 2, "skipped": 0, "empty": 0}


def test_write_missing_ignores_articles_without_content(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    make.article(title="No content", digest_date=DAY)
    llm = FakeLLM(lambda _, __: VALID)

    write_missing(context(sessions), llm, ENGLISH, DAY)

    assert llm.prompts == []


def test_write_missing_reads_the_interests(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    make.interest("Postgres", keywords=["pgvector"])
    digest_article(make, "First", DAY)
    llm = FakeLLM(lambda _, __: VALID)

    write_missing(context(sessions, started_at=NOW), llm, ENGLISH, DAY)

    assert "- Postgres: pgvector" in llm.prompts[0]
