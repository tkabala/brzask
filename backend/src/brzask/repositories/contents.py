"""The full text of picked articles."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brzask.db.models import ArticleContent, ContentKind


class ContentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, article_id: int, text: str, kind: ContentKind, extracted_by: str | None) -> None:
        """Store the text of an article; an article keeps the text it was first stored with."""
        self.session.execute(
            insert(ArticleContent)
            .values(article_id=article_id, text=text, kind=kind, extracted_by=extracted_by)
            .on_conflict_do_nothing(index_elements=[ArticleContent.article_id])
        )

    def get(self, article_id: int) -> ArticleContent | None:
        return self.session.get(ArticleContent, article_id)
