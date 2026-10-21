"""Login sessions, stored as hashes of their cookie values."""

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from brzask.db.models import LoginSession


class LoginSessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, token_hash: str, expires_at: datetime) -> LoginSession:
        login = LoginSession(token_hash=token_hash, expires_at=expires_at)
        self.session.add(login)
        self.session.flush()
        return login

    def find_valid(self, token_hash: str, now: datetime) -> LoginSession | None:
        """The session with this hash, unless it has expired."""
        query = select(LoginSession).where(
            LoginSession.token_hash == token_hash, LoginSession.expires_at > now
        )
        return self.session.scalars(query).one_or_none()

    def touch(self, login: LoginSession, used_at: datetime) -> None:
        login.last_used_at = used_at
        self.session.flush()

    def delete(self, token_hash: str) -> bool:
        result = self.session.execute(
            delete(LoginSession).where(LoginSession.token_hash == token_hash)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def delete_expired(self, now: datetime) -> int:
        result = self.session.execute(delete(LoginSession).where(LoginSession.expires_at <= now))
        return int(result.rowcount)  # type: ignore[attr-defined]
