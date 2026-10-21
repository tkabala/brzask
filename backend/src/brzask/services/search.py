"""Semantic search over stored articles."""

from typing import Protocol

from sqlalchemy.orm import Session

from brzask.clients.embeddings import EmbeddingKind
from brzask.repositories import ArticleRepository
from brzask.repositories.articles import SimilarArticle
from brzask.services.errors import ServiceError


class QueryEmbedder(Protocol):
    """Embeds texts (`Embedder`) with one model."""

    model: str

    def embed(
        self, texts: list[str], kind: EmbeddingKind, *, purpose: str = "embedding"
    ) -> list[list[float]]: ...


def search_articles(
    session: Session, embedder: QueryEmbedder, query: str, limit: int
) -> list[SimilarArticle]:
    """Articles nearest to `query`, among vectors of the embedder's model.

    The query is embedded as a query, not a document: retrieval models embed
    the two differently, so a short question still lands near the articles
    that answer it.
    """
    query = query.strip()
    if not query:
        raise ServiceError("the search query must not be empty")
    [vector] = embedder.embed([query], "query", purpose="search")
    return ArticleRepository(session).search_similar(vector, embedder.model, limit)
