from sqlalchemy.orm import Session

from brzask.db.models import ContentKind
from brzask.repositories import ContentRepository
from tests.factories import Factories


def test_save_and_get(session: Session, make: Factories) -> None:
    article = make.article()
    contents = ContentRepository(session)

    contents.save(article.id, "Full text", ContentKind.PAGE, "trafilatura")

    stored = contents.get(article.id)
    assert stored is not None
    assert (stored.text, stored.kind, stored.extracted_by) == (
        "Full text",
        ContentKind.PAGE,
        "trafilatura",
    )
    assert stored.fetched_at is not None


def test_get_without_content(session: Session, make: Factories) -> None:
    assert ContentRepository(session).get(make.article().id) is None


def test_forced_run_keeps_existing_content(session: Session, make: Factories) -> None:
    article = make.article()
    contents = ContentRepository(session)

    contents.save(article.id, "First", ContentKind.PAGE, "trafilatura")
    contents.save(article.id, "Second", ContentKind.DESCRIPTION, None)

    stored = contents.get(article.id)
    assert stored is not None
    assert (stored.text, stored.kind) == ("First", ContentKind.PAGE)
