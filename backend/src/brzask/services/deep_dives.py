"""Requesting, listing and exporting deep dives (the writing is `services.deep_dive`)."""

from collections.abc import Sequence
from datetime import datetime, tzinfo

from sqlalchemy.orm import Session

from brzask.config.settings import BudgetSettings
from brzask.db.models import DeepDive, DeepDiveStatus
from brzask.prompts import Language
from brzask.repositories import ContentRepository, DeepDiveRepository
from brzask.repositories.deep_dives import DuplicateDeepDiveError
from brzask.services.budget import check_budget
from brzask.services.deep_dive import markdown
from brzask.services.digests import get_article
from brzask.services.errors import ConflictError, NotFoundError

NO_CONTENT = "this article has no stored text to go deeper from"


def start_reason(
    session: Session, article_id: int, now: datetime, budget: BudgetSettings, tz: tzinfo
) -> str | None:
    """Why a deep dive of the article cannot start now; None when it can."""
    if ContentRepository(session).get(article_id) is None:
        return NO_CONTENT
    state = check_budget(session, now, budget, tz)
    return state.reason if state is not None else None


def article_dives(
    session: Session, article_id: int, now: datetime, budget: BudgetSettings, tz: tzinfo
) -> tuple[Sequence[DeepDive], str | None]:
    """The article's dives, newest first, and why a new one cannot start (None: it can)."""
    get_article(session, article_id)
    reason = start_reason(session, article_id, now, budget, tz)
    return DeepDiveRepository(session).for_article(article_id), reason


def request_dive(
    session: Session,
    article_id: int,
    focus: str,
    now: datetime,
    budget: BudgetSettings,
    tz: tzinfo,
) -> DeepDive:
    """A queued dive; NotFoundError for an unknown article, ConflictError when it cannot start."""
    get_article(session, article_id)
    reason = start_reason(session, article_id, now, budget, tz)
    if reason is not None:
        raise ConflictError(reason)
    try:
        return DeepDiveRepository(session).create(article_id, focus)
    except DuplicateDeepDiveError:
        raise ConflictError(
            "a deep dive of this article with the same focus is already being written"
        ) from None


def get_dive(session: Session, dive_id: int) -> DeepDive:
    dive = DeepDiveRepository(session).get(dive_id)
    if dive is None:
        raise NotFoundError(f"no deep dive {dive_id}")
    return dive


def retry_dive(
    session: Session, dive_id: int, now: datetime, budget: BudgetSettings, tz: tzinfo
) -> DeepDive:
    """A new queued dive with the failed one's article and focus."""
    dive = get_dive(session, dive_id)
    if dive.status is not DeepDiveStatus.FAILED:
        raise ConflictError("only a failed deep dive can be tried again")
    return request_dive(session, dive.article_id, dive.focus, now, budget, tz)


def mark_read(session: Session, dive_id: int, now: datetime) -> None:
    if not DeepDiveRepository(session).mark_read(dive_id, now):
        raise NotFoundError(f"no deep dive {dive_id}")


def export_markdown(session: Session, dive_id: int, language: Language) -> tuple[str, str]:
    """The finished dive as Markdown, and its file name."""
    dive = get_dive(session, dive_id)
    if dive.status is not DeepDiveStatus.DONE:
        raise ConflictError("the deep dive is not finished")
    return markdown.render(dive, dive.article, language), markdown.filename(dive, dive.article)
