"""Data access, one repository per aggregate.

Repositories take a `Session`, flush when callers need generated values, and
never commit: the service calling them owns the transaction. Time windows are
passed in as explicit `since` timestamps rather than computed from `now()`, so
the same queries work when re-running past days.
"""

from brzask.repositories.articles import ArticleRepository
from brzask.repositories.changes import ChangeRepository
from brzask.repositories.embeddings import EmbeddingRepository
from brzask.repositories.interests import InterestRepository
from brzask.repositories.login_sessions import LoginSessionRepository
from brzask.repositories.runs import RunRepository
from brzask.repositories.settings import SettingRepository
from brzask.repositories.sources import SourceRepository
from brzask.repositories.tokens import ApiTokenRepository

__all__ = [
    "ApiTokenRepository",
    "ArticleRepository",
    "ChangeRepository",
    "EmbeddingRepository",
    "InterestRepository",
    "LoginSessionRepository",
    "RunRepository",
    "SettingRepository",
    "SourceRepository",
]
