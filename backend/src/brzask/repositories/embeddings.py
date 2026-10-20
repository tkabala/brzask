"""Article vectors, one per article and embedding model."""

from collections.abc import Collection, Mapping, Sequence

from sqlalchemy import ColumnElement, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from brzask.db.models import Article, ArticleEmbedding


class EmbeddingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, model: str, vectors: Mapping[int, Sequence[float]]) -> None:
        """Store vectors by article ID, replacing the article's earlier vector of `model`."""
        if not vectors:
            return
        statement = insert(ArticleEmbedding).values(
            [
                {"article_id": article_id, "model": model, "embedding": list(vector)}
                for article_id, vector in vectors.items()
            ]
        )
        statement = statement.on_conflict_do_update(
            index_elements=[ArticleEmbedding.article_id, ArticleEmbedding.model],
            set_={"embedding": statement.excluded.embedding, "created_at": func.now()},
        )
        self.session.execute(statement)

    def of_articles(self, article_ids: Collection[int], model: str) -> dict[int, list[float]]:
        """The `model` vectors of these articles; articles without one are left out."""
        if not article_ids:
            return {}
        query = select(ArticleEmbedding.article_id, ArticleEmbedding.embedding).where(
            ArticleEmbedding.model == model, ArticleEmbedding.article_id.in_(article_ids)
        )
        return {article_id: list(vector) for article_id, vector in self.session.execute(query)}

    def missing(self, model: str, limit: int) -> list[tuple[int, str]]:
        """Articles with a vector of another model but none of `model`, with their text.

        Those are what `model` has to embed before it can replace the others;
        articles without stored text cannot be embedded again and are left out.
        """
        query = (
            select(Article.id, Article.extracted_text)
            .where(self._missing(model), Article.extracted_text != "")
            .order_by(Article.id)
            .limit(limit)
        )
        return [(article_id, text or "") for article_id, text in self.session.execute(query)]

    def count_missing(self, model: str) -> tuple[int, int]:
        """Articles `missing` would return, and those it cannot because they have no text."""
        has_text = Article.extracted_text != ""  # NULL is neither
        query = select(
            func.count().filter(has_text),
            func.count().filter(~func.coalesce(has_text, False)),
        ).where(self._missing(model))
        with_text, without_text = self.session.execute(query).one()
        return with_text, without_text

    def counts_by_model(self) -> dict[str, int]:
        query = select(ArticleEmbedding.model, func.count()).group_by(ArticleEmbedding.model)
        return {model: count for model, count in self.session.execute(query)}

    @staticmethod
    def _missing(model: str) -> ColumnElement[bool]:
        other, same = aliased(ArticleEmbedding), aliased(ArticleEmbedding)
        has_other = exists().where(other.article_id == Article.id, other.model != model)
        has_same = exists().where(same.article_id == Article.id, same.model == model)
        return has_other & ~has_same
