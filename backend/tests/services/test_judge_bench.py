from datetime import timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from brzask.services.digest.scoring import DIMENSIONS
from brzask.services.judge_bench import auc, report, score_shown
from tests.factories import Factories
from tests.services.digest.fakes import NOW, FakeJudge

TODAY = NOW.date()
YESTERDAY = TODAY - timedelta(days=1)


@pytest.mark.parametrize(
    ("scores", "opened", "expected"),
    [
        ([0.9, 0.1, 0.2], [True, False, False], 1.0),
        ([0.1, 0.9, 0.2], [True, False, False], 0.0),
        ([0.5, 0.5], [True, False], 0.5),
        ([0.9, 0.3, 0.5, 0.1], [True, True, False, False], 0.75),
        ([0.9, 0.1], [True, True], None),
    ],
)
def test_auc(scores: list[float], opened: list[bool], expected: float | None) -> None:
    assert auc(scores, opened) == expected


def test_shown_articles_of_each_first_run_are_scored_with_the_opens_before_it(
    sessions: sessionmaker[Session], make: Factories
) -> None:
    make.interest("Postgres")
    source = make.source("Blog")
    yesterday_run, today_run = NOW - timedelta(days=1), NOW
    for title, day, run, opened in [
        ("Opened yesterday", YESTERDAY, yesterday_run, yesterday_run + timedelta(hours=2)),
        ("Ignored yesterday", YESTERDAY, yesterday_run, None),
        ("Ignored today", TODAY, today_run, None),
        ("Opened today", TODAY, today_run, today_run + timedelta(hours=1)),
    ]:
        make.article(
            source,
            title=title,
            first_seen_at=run - timedelta(hours=1),
            digest_date=day,
            shown_at=run,
            opened_at=opened,
        )
    make.article(  # appended by a forced run later today: not scored
        source,
        title="Forced",
        first_seen_at=today_run,
        digest_date=TODAY,
        shown_at=today_run + timedelta(hours=5),
    )
    judge = FakeJudge(
        {
            "Opened yesterday": {"interest_fit": 4, "depth": 2},
            "Opened today": {"interest_fit": 4},
            "Ignored today": {"depth": 2},
        },
    )

    result = score_shown(sessions, judge, YESTERDAY, workers=2)

    assert sorted((row.day, row.title, row.opened) for row in result.rows) == [
        (YESTERDAY, "Ignored yesterday", False),
        (YESTERDAY, "Opened yesterday", True),
        (TODAY, "Ignored today", False),
        (TODAY, "Opened today", True),
    ]
    opened_yesterday = next(row for row in result.rows if row.title == "Opened yesterday")
    assert opened_yesterday.scores == {name: 0.0 for name in DIMENSIONS} | {
        "interest_fit": 1.0,
        "depth": 1.0,
    }
    aucs = result.aucs()
    assert aucs["interest_fit"] == 1.0
    assert aucs["depth"] == 0.5
    assert aucs["novelty"] == 0.5
    # Today's state lists what was opened before today's run.
    today_state = next(s for s in judge.states if s["article"]["title"] == "Opened today")
    assert today_state["reader"]["recently_opened"] == ["Opened yesterday"]
    assert result.usage["calls"] == 4
    assert result.failed == 0

    data = report([result])
    assert data["models"][0]["opened"] == 2
    assert data["models"][0]["auc"]["composite"] == 1.0
    assert len(data["models"][0]["rows"]) == 4


def test_articles_the_judge_cannot_answer_are_counted(
    sessions: sessionmaker[Session], make: Factories
) -> None:
    source = make.source()
    for title in ("A", "B"):
        make.article(source, title=title, digest_date=TODAY, shown_at=NOW)

    result = score_shown(sessions, FakeJudge(fail={"A"}), TODAY)

    assert [row.title for row in result.rows] == ["B"]
    assert result.failed == 1


def test_a_day_the_judge_cannot_answer_at_all_is_counted_not_fatal(
    sessions: sessionmaker[Session], make: Factories
) -> None:
    source = make.source()
    make.article(source, title="A", digest_date=TODAY, shown_at=NOW)

    result = score_shown(sessions, FakeJudge(fail={"A"}), TODAY)

    assert result.rows == []
    assert result.failed == 1
