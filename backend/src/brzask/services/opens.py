"""Opening an article: the only preference signal."""

from datetime import datetime
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from brzask.db.models import Article
from brzask.repositories import ArticleRepository
from brzask.services.errors import NotFoundError, ServiceError


def article_link(session: Session, article_id: int) -> str:
    """Where the article lives; only web links are followed."""
    article = session.get(Article, article_id)
    if article is None:
        raise NotFoundError(f"no article {article_id}")
    if urlsplit(article.link).scheme not in {"http", "https"}:
        raise ServiceError(f"article {article_id} has no web link")
    return article.link


def open_article(session: Session, article_id: int, now: datetime) -> str:
    """Record that the article was opened and return its link.

    Only the first open is kept, so following the link again, from the digest,
    a feed reader or a bookmark, changes nothing.
    """
    link = article_link(session, article_id)
    ArticleRepository(session).record_open(article_id, now)
    return link
