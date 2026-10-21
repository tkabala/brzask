"""Semantic search."""

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from brzask.api import problems
from brzask.api.articles import ArticleOut
from brzask.api.deps import NO_NUL, Clients, DbSession
from brzask.config import get_settings
from brzask.services.embeddings import active_model
from brzask.services.search import search_articles

router = APIRouter(prefix="/search", tags=["search"])

MAX_RESULTS = 50


class SearchHit(BaseModel):
    article: ArticleOut
    similarity: float = Field(description="Cosine similarity to the query, at most 1.")


class SearchResults(BaseModel):
    model: str = Field(description="Embedding model of the query and the articles.")
    items: list[SearchHit] = Field(description="Most similar first.")


@router.get(
    "",
    summary="Search articles by meaning",
    responses=problems.responses(HTTPStatus.BAD_REQUEST, HTTPStatus.BAD_GATEWAY),
)
def search(
    session: DbSession,
    clients: Clients,
    q: Annotated[
        str, Query(min_length=1, max_length=500, pattern=NO_NUL, description="What to look for.")
    ],
    limit: Annotated[int, Query(ge=1, le=MAX_RESULTS, description="How many results.")] = 20,
) -> SearchResults:
    """Articles whose text is closest in meaning to `q`, read or not, shown or not.

    Not paginated: results are the nearest `limit`, and further ones are rarely
    worth reading.
    """
    embedder = clients.embedder(active_model(session, get_settings().embedding.model))
    hits = search_articles(session, embedder, q, limit)
    return SearchResults(
        model=embedder.model,
        items=[SearchHit(article=ArticleOut.of(h.article), similarity=h.similarity) for h in hits],
    )
