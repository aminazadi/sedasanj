from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import PlatformSetting
from app.routers import admin
from app.schemas import SettingsUpdate
from app.services import platform


class _FakeSession:
    def __init__(self, row: PlatformSetting | None = None) -> None:
        self.saved: dict[str, PlatformSetting] = {}
        self._row = row

    async def get(self, model: object, key: str) -> PlatformSetting | None:
        if key in self.saved:
            return self.saved[key]
        return self._row if self._row is not None and self._row.key == key else None

    def add(self, row: PlatformSetting) -> None:
        self.saved[row.key] = row

    async def flush(self) -> None:
        pass


def test_flag_is_a_known_setting_and_defaults_to_off() -> None:
    assert "jalase_standalone_enabled" in platform.OVERRIDE_KEYS
    assert SettingsUpdate().jalase_standalone_enabled is None


@pytest.mark.asyncio
async def test_reader_is_off_without_a_row_and_follows_the_stored_value() -> None:
    assert await platform.jalase_standalone_enabled(_FakeSession()) is False  # type: ignore[arg-type]
    on = PlatformSetting(key="jalase_standalone_enabled", value="true")
    assert await platform.jalase_standalone_enabled(_FakeSession(on)) is True  # type: ignore[arg-type]
    off = PlatformSetting(key="jalase_standalone_enabled", value="false")
    assert await platform.jalase_standalone_enabled(_FakeSession(off)) is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_admin_update_persists_and_audits_the_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audited: dict[str, object] = {}

    async def fake_audit(*args: object, **kwargs: object) -> None:
        audited.update(kwargs.get("payload") or {})  # type: ignore[call-overload]

    async def fake_view(session: object) -> dict[str, object]:
        return {}

    monkeypatch.setattr(admin.audit, "record", fake_audit)
    monkeypatch.setattr(admin, "settings_public_view", fake_view)
    monkeypatch.setattr(admin, "client_ip", lambda request: "127.0.0.1")
    session = _FakeSession()
    await admin.update_platform_settings(
        SettingsUpdate(jalase_standalone_enabled=True),
        None,  # type: ignore[arg-type]
        type("S", (), {"id": uuid4()})(),  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
    )
    assert session.saved["jalase_standalone_enabled"].value.lower() == "true"
    assert "jalase_standalone_enabled" in audited["changed_settings"]  # type: ignore[operator]
