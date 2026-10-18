from sqlalchemy.orm import Session

from brzask.repositories import SettingRepository


def test_put_inserts_then_replaces(session: Session) -> None:
    settings = SettingRepository(session)
    assert settings.get("pause") is None

    settings.put("pause", {"until": "2026-10-20"})
    assert settings.get("pause") == {"until": "2026-10-20"}

    settings.put("pause", {"until": "2026-10-25"})
    assert settings.get("pause") == {"until": "2026-10-25"}


def test_delete(session: Session) -> None:
    settings = SettingRepository(session)
    settings.put("pause", {"until": "2026-10-20"})

    settings.delete("pause")
    settings.delete("never-set")

    assert settings.get("pause") is None
