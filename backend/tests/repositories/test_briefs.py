from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from brzask.db.models import Article, ArticleContent, BriefBasis, ContentKind
from brzask.repositories import BriefRepository
from brzask.services.briefs import Brief, Chapter
from tests.factories import Factories

DAY = date(2026, 11, 16)
BRIEF = Brief(
    gist="The gist.",
    points=["one", "two", "three"],
    caveats=["a vendor post"],
    chapters=[Chapter(0, "Intro"), Chapter(95, "Demo")],
)


def with_content(make: Factories, day: date | None, position: int | None = None) -> int:
    article = make.article(digest_date=day, digest_position=position)
    make.session.add(ArticleContent(article_id=article.id, text="Text", kind=ContentKind.PAGE))
    make.session.flush()
    return article.id


def test_save_and_get(session: Session, make: Factories) -> None:
    article_id = with_content(make, DAY)
    repository = BriefRepository(session)

    repository.save(article_id, BRIEF, BriefBasis.TRANSCRIPT, "test/model")

    stored = repository.get(article_id)
    assert stored is not None
    assert (stored.gist, stored.points, stored.caveats) == (
        "The gist.",
        ["one", "two", "three"],
        ["a vendor post"],
    )
    assert stored.chapters == [{"start": 0, "title": "Intro"}, {"start": 95, "title": "Demo"}]
    assert (stored.basis, stored.model) == (BriefBasis.TRANSCRIPT, "test/model")
    assert stored.created_at is not None


def test_get_without_a_brief(session: Session, make: Factories) -> None:
    assert BriefRepository(session).get(make.article().id) is None


def test_a_second_save_keeps_the_first_brief(session: Session, make: Factories) -> None:
    article_id = with_content(make, DAY)
    repository = BriefRepository(session)

    repository.save(article_id, BRIEF, BriefBasis.FULL_TEXT, "first/model")
    repository.save(article_id, Brief("Other.", ["x"] * 3, [], []), BriefBasis.PARTIAL, "other")

    session.expire_all()
    stored = repository.get(article_id)
    assert stored is not None
    assert (stored.gist, stored.model) == ("The gist.", "first/model")


def test_missing_lists_recent_digest_articles_with_content_and_no_brief(
    session: Session, make: Factories
) -> None:
    later = with_content(make, DAY, position=2)
    earlier = with_content(make, DAY, position=1)
    yesterday = with_content(make, date(2026, 11, 15))
    briefed = with_content(make, DAY, position=3)
    with_content(make, date(2026, 11, 14))  # before `since`
    with_content(make, None)  # never in a digest
    make.article(digest_date=DAY, digest_position=4)  # no content
    repository = BriefRepository(session)
    repository.save(briefed, BRIEF, BriefBasis.FULL_TEXT, "test/model")

    missing = repository.missing(since=date(2026, 11, 15))

    assert [article.id for article, _ in missing] == [yesterday, earlier, later]
    assert all(content.article_id == article.id for article, content in missing)


def test_ids_with_brief(session: Session, make: Factories) -> None:
    briefed = with_content(make, DAY)
    other = with_content(make, DAY)
    repository = BriefRepository(session)
    repository.save(briefed, BRIEF, BriefBasis.FULL_TEXT, "test/model")

    assert repository.ids_with_brief([briefed, other, 999_999]) == {briefed}
    assert repository.ids_with_brief([]) == set()


def test_deleting_the_article_deletes_its_brief(session: Session, make: Factories) -> None:
    article_id = with_content(make, DAY)
    repository = BriefRepository(session)
    repository.save(article_id, BRIEF, BriefBasis.FULL_TEXT, "test/model")

    session.execute(delete(Article).where(Article.id == article_id))
    session.expire_all()

    assert repository.get(article_id) is None
