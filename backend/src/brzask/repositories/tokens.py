"""API tokens, stored as hashes."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from brzask.db.models import ApiToken, TokenScope


class ApiTokenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, *, name: str, prefix: str, token_hash: str, scope: TokenScope) -> ApiToken:
        token = ApiToken(name=name, prefix=prefix, token_hash=token_hash, scope=scope)
        self.session.add(token)
        self.session.flush()
        return token

    def get_by_name(self, name: str) -> ApiToken | None:
        query = select(ApiToken).where(ApiToken.name == name)
        return self.session.scalars(query).one_or_none()

    def find_usable(self, token_hash: str) -> ApiToken | None:
        """The token with this hash, unless it was revoked."""
        query = select(ApiToken).where(
            ApiToken.token_hash == token_hash, ApiToken.revoked_at.is_(None)
        )
        return self.session.scalars(query).one_or_none()

    def find(self) -> Sequence[ApiToken]:
        return self.session.scalars(select(ApiToken).order_by(ApiToken.name)).all()

    def touch(self, token: ApiToken, used_at: datetime) -> None:
        token.last_used_at = used_at
        self.session.flush()

    def revoke(self, token: ApiToken, revoked_at: datetime) -> None:
        if token.revoked_at is None:
            token.revoked_at = revoked_at
            self.session.flush()
