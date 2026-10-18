"""Values changed at runtime, such as a pause."""

from typing import Any

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brzask.db.models import Setting


class SettingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, key: str) -> dict[str, Any] | None:
        # The upsert in `put` bypasses the identity map; always read the stored row.
        setting = self.session.get(Setting, key, populate_existing=True)
        return setting.value if setting else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        statement = insert(Setting).values(key=key, value=value)
        statement = statement.on_conflict_do_update(
            index_elements=[Setting.key],
            set_={"value": statement.excluded.value, "updated_at": func.now()},
        )
        self.session.execute(statement)

    def delete(self, key: str) -> None:
        self.session.execute(delete(Setting).where(Setting.key == key))
