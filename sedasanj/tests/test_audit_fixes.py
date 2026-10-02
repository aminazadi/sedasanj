from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.deps import Principal
from app.errors import ApiError
from app.models import Call, PlatformSetting
from app.routers import admin, calls
from app.schemas import SettingsUpdate
from worker_asr import main as asr_main
from worker_llm.client import LlamaClient


class _Result:
    def __init__(self, *, scalar: object | None = None, first: object | None = None) -> None:
        self.scalar = scalar
        self._first = first

    def scalar_one_or_none(self) -> object | None:
        return self.scalar

    def scalars(self) -> _Result:
        return self

    def first(self) -> object | None:
        return self._first


@pytest.mark.asyncio
async def test_asr_fallback_run_uses_persisted_platform_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = {"llm_model": "staff-llama", "prompt_version": "staff-prompt"}

    async def persisted_models(session: AsyncSession) -> dict[str, str]:
        return models

    async def persisted_prompt(session: AsyncSession, prompt_version: str) -> str:
        assert prompt_version == "staff-prompt"
        return "staff system prompt"

    session = AsyncSession()
    execute = AsyncMock(return_value=_Result())
    add = Mock()
    monkeypatch.setattr(asr_main, "effective_models", persisted_models)
    monkeypatch.setattr(asr_main, "effective_extract_prompt", persisted_prompt)
    monkeypatch.setattr(session, "execute", execute)
    monkeypatch.setattr(session, "add", add)
    try:
        run = await asr_main._load_or_create_analysis_run(session, uuid4(), uuid4())
    finally:
        await session.close()

    assert run.llm_model == "staff-llama"
    assert run.prompt_version == "staff-prompt"
    assert run.system_prompt == "staff system prompt"
    add.assert_called_once_with(run)


@pytest.mark.asyncio
async def test_reanalysis_rejects_a_retryable_llm_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager

    call_id = uuid4()
    tenant_id = uuid4()
    call = Call(id=call_id, tenant_id=tenant_id)

    async def load_call(
        session: AsyncSession,
        requested_call_id: object,
        requested_tenant_id: object,
        principal: object | None = None,
    ) -> Call:
        assert requested_call_id == call_id
        assert requested_tenant_id == tenant_id
        return call

    session = AsyncSession()
    execute = AsyncMock(side_effect=[_Result(scalar=object()), _Result(first=object())])
    monkeypatch.setattr(session, "execute", execute)
    monkeypatch.setattr(calls, "_load_call", load_call)

    @asynccontextmanager
    async def fake_scope(*args: object, **kwargs: object):
        yield session

    monkeypatch.setattr(calls, "session_scope", fake_scope)
    principal = Principal(kind="user", id=uuid4(), tenant_id=tenant_id, role="operator")

    try:
        with pytest.raises(ApiError, match="already queued"):
            await calls.reanalyze_call(
                call_id,
                None,  # type: ignore[arg-type]
                principal,
            )
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_reanalysis_explains_when_transcript_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager

    call_id = uuid4()
    tenant_id = uuid4()
    call = Call(id=call_id, tenant_id=tenant_id)

    async def load_call(
        session: AsyncSession,
        requested_call_id: object,
        requested_tenant_id: object,
        principal: object | None = None,
    ) -> Call:
        assert requested_call_id == call_id
        assert requested_tenant_id == tenant_id
        return call

    session = AsyncSession()
    execute = AsyncMock(return_value=_Result(scalar=None))
    monkeypatch.setattr(session, "execute", execute)
    monkeypatch.setattr(calls, "_load_call", load_call)

    @asynccontextmanager
    async def fake_scope(*args: object, **kwargs: object):
        yield session

    monkeypatch.setattr(calls, "session_scope", fake_scope)
    principal = Principal(kind="user", id=uuid4(), tenant_id=tenant_id, role="operator")

    try:
        with pytest.raises(ApiError, match="متن تماس هنوز آماده نشده"):
            await calls.reanalyze_call(
                call_id,
                None,  # type: ignore[arg-type]
                principal,
            )
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_requeue_enqueues_only_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime

    from app.models import Job

    job_id = uuid4()
    call_id = uuid4()
    tenant_id = uuid4()
    events: list[str] = []

    job = Job(
        id=job_id,
        tenant_id=tenant_id,
        call_id=call_id,
        kind="asr",
        status="failed_terminal",
        attempt=3,
        run_after=datetime.now(UTC),
    )
    call = Call(id=call_id, tenant_id=tenant_id, status="failed_terminal")

    class FakeSession:
        async def get(self, model: object, key: object) -> object | None:
            if model is Job and key == job_id:
                return job
            return None

        async def execute(self, statement: object) -> _Result:
            return _Result(scalar=call)

        async def flush(self) -> None:
            return None

    @asynccontextmanager
    async def fake_scope(*args: object, **kwargs: object):
        events.append("begin")
        try:
            yield FakeSession()
            events.append("commit")
        except BaseException:
            events.append("rollback")
            raise

    async def fake_stage_job(*args: object, **kwargs: object):
        events.append("stage")
        return uuid4()

    async def fake_resolve_tenant(value: object) -> UUID:
        return tenant_id

    async def fake_dispatch(outbox_id: object) -> bool:
        assert "commit" in events
        events.append(f"dispatch:{outbox_id}")
        return True

    async def fake_processing_event(*args: object, **kwargs: object) -> None:
        events.append("processing_event")

    async def fake_audit(*args: object, **kwargs: object) -> None:
        events.append("audit")

    monkeypatch.setattr(admin, "session_scope", fake_scope)
    monkeypatch.setattr(admin, "resolve_tenant_for_job", fake_resolve_tenant)
    monkeypatch.setattr(admin.outbox, "stage_job", fake_stage_job)
    monkeypatch.setattr(admin.outbox, "dispatch_one", fake_dispatch)
    monkeypatch.setattr(admin.processing_events, "record", fake_processing_event)
    monkeypatch.setattr(admin.audit, "record", fake_audit)
    monkeypatch.setattr(admin, "client_ip", lambda request: "127.0.0.1")
    monkeypatch.setattr(
        admin.progress,
        "values_for_status",
        lambda status: {"progress_pct": 10, "progress_detail": status},
    )

    staff = type("S", (), {"id": uuid4()})()
    result = await admin.requeue_job(job_id, None, staff)  # type: ignore[arg-type]
    assert result == {"status": "queued", "job_id": str(job_id)}
    assert events[:4] == ["begin", "audit", "processing_event", "stage"]
    assert events[4] == "commit"
    assert events[5].startswith("dispatch:")
    assert job.status == "queued"
    assert call.status == "stored"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        SettingsUpdate(llm_model=" "),
        SettingsUpdate(asr_model="\t"),
    ],
)
async def test_settings_update_rejects_blank_values(payload: SettingsUpdate) -> None:
    with pytest.raises(ApiError, match="must not be empty"):
        await admin.update_platform_settings(payload, None, None, None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_settings_update_requires_key_for_voicesanj_llm() -> None:
    class FakeSession:
        async def get(self, model: object, key: str) -> None:
            return None

    with pytest.raises(ApiError, match="LLM API key is required"):
        await admin.update_platform_settings(
            SettingsUpdate(llm_provider="voicesanj"),
            None,
            None,
            FakeSession(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("value", [0, 4])
def test_settings_update_limits_global_analysis_concurrency(value: int) -> None:
    with pytest.raises(ValueError):
        SettingsUpdate(analysis_concurrency=value)


@pytest.mark.asyncio
async def test_settings_update_persists_global_analysis_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: dict[str, PlatformSetting] = {}

    class FakeSession:
        async def get(self, model: object, key: str) -> PlatformSetting | None:
            return saved.get(key)

        def add(self, row: PlatformSetting) -> None:
            saved[row.key] = row

        async def flush(self) -> None:
            pass

    async def fake_audit(*args: object, **kwargs: object) -> None:
        pass

    async def fake_view(session: object) -> dict[str, object]:
        return {"analysis_concurrency": int(saved["analysis_concurrency"].value)}

    monkeypatch.setattr(admin.audit, "record", fake_audit)
    monkeypatch.setattr(admin, "settings_public_view", fake_view)
    monkeypatch.setattr(admin, "client_ip", lambda request: "127.0.0.1")

    result = await admin.update_platform_settings(
        SettingsUpdate(analysis_concurrency=2),
        None,  # type: ignore[arg-type]
        type("S", (), {"id": uuid4()})(),  # type: ignore[arg-type]
        FakeSession(),  # type: ignore[arg-type]
    )

    assert saved["analysis_concurrency"].value == "2"
    assert result["analysis_concurrency"] == 2


@pytest.mark.asyncio
async def test_settings_update_persists_and_redacts_ninerouter_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: dict[str, PlatformSetting] = {}
    seen: dict[str, object] = {}

    class FakeSession:
        async def get(self, model: object, key: str) -> PlatformSetting | None:
            return saved.get(key)

        def add(self, row: PlatformSetting) -> None:
            saved[row.key] = row

        async def flush(self) -> None:
            pass

    async def fake_audit(*args: object, **kwargs: object) -> None:
        seen["audit"] = kwargs.get("payload")

    async def fake_view(session: object) -> dict[str, object]:
        return {key: row.value for key, row in saved.items()}

    monkeypatch.setattr(admin.audit, "record", fake_audit)
    monkeypatch.setattr(admin, "settings_public_view", fake_view)
    monkeypatch.setattr(admin, "client_ip", lambda request: "127.0.0.1")

    result = await admin.update_platform_settings(
        SettingsUpdate(
            ninerouter_asr_prompt="  واژگان تخصصی را حفظ کن  ",
            ninerouter_analysis_prompt="تحلیل تکمیلی",
            ninerouter_chat_prompt="راهنمای دستیار",
            ninerouter_decision_prompt="قاعده تصمیم",
        ),
        None,  # type: ignore[arg-type]
        type("S", (), {"id": uuid4()})(),  # type: ignore[arg-type]
        FakeSession(),  # type: ignore[arg-type]
    )

    assert result == {
        "ninerouter_asr_prompt": "واژگان تخصصی را حفظ کن",
        "ninerouter_analysis_prompt": "تحلیل تکمیلی",
        "ninerouter_chat_prompt": "راهنمای دستیار",
        "ninerouter_decision_prompt": "قاعده تصمیم",
    }
    assert seen["audit"] == dict.fromkeys(result, "updated")


@pytest.mark.asyncio
async def test_settings_update_ignores_blank_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class FakeSession:
        async def get(self, model: object, key: str) -> None:
            seen["get"] = key
            return None

        def add(self, row: object) -> None:
            seen["add"] = row

        async def flush(self) -> None:
            seen["flushed"] = True

    async def fake_audit(*args: object, **kwargs: object) -> None:
        seen["audit"] = kwargs.get("payload")

    async def fake_view(session: object) -> dict[str, object]:
        return {
            "asr_model": "a",
            "llm_model": "b",
            "prompt_version": "c",
            "api_key_configured": False,
            "api_key_hint": "",
        }

    monkeypatch.setattr(admin.audit, "record", fake_audit)
    monkeypatch.setattr(admin, "settings_public_view", fake_view)
    monkeypatch.setattr(admin, "client_ip", lambda request: "127.0.0.1")

    staff = type("S", (), {"id": uuid4()})()
    result = await admin.update_platform_settings(
        SettingsUpdate(api_key="   "),
        None,  # type: ignore[arg-type]
        staff,  # type: ignore[arg-type]
        FakeSession(),  # type: ignore[arg-type]
    )
    assert "get" not in seen
    assert seen.get("audit") == {}
    assert result["api_key_configured"] is False


@pytest.mark.asyncio
async def test_settings_update_normalizes_and_validates_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    class FakeSession:
        async def get(self, model: object, key: str) -> None:
            seen["get"] = key
            return None

        def add(self, row: object) -> None:
            seen["row"] = row

        async def flush(self) -> None:
            seen["flushed"] = True

    async def fake_audit(*args: object, **kwargs: object) -> None:
        seen["audit"] = kwargs.get("payload")

    async def fake_view(session: object) -> dict[str, object]:
        return {
            "asr_model": "a",
            "llm_model": "b",
            "prompt_version": "c",
            "api_key_configured": True,
            "api_key_hint": "••••cret",
        }

    async def fake_validate(api_key: str) -> None:
        seen["validated"] = api_key

    monkeypatch.setattr(admin.audit, "record", fake_audit)
    monkeypatch.setattr(admin, "settings_public_view", fake_view)
    monkeypatch.setattr(admin, "_validate_voicesanj_api_key", fake_validate)
    monkeypatch.setattr(admin, "client_ip", lambda request: "127.0.0.1")

    staff = type("S", (), {"id": uuid4()})()
    result = await admin.update_platform_settings(
        SettingsUpdate(api_key='  "quoted-secret"  '),
        None,  # type: ignore[arg-type]
        staff,  # type: ignore[arg-type]
        FakeSession(),  # type: ignore[arg-type]
    )
    assert seen["validated"] == "quoted-secret"
    assert isinstance(seen["row"], PlatformSetting)
    assert seen["row"].value == "quoted-secret"
    assert seen["audit"] == {"api_key": "••••cret"}
    assert result["api_key_configured"] is True


@pytest.mark.asyncio
async def test_settings_update_persists_independent_9router_asr_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    added: list[PlatformSetting] = []
    seen: dict[str, object] = {}

    class FakeSession:
        async def get(self, model: object, key: str) -> None:
            return None

        def add(self, row: PlatformSetting) -> None:
            added.append(row)

        async def flush(self) -> None:
            return None

    async def fake_audit(*args: object, **kwargs: object) -> None:
        seen["audit"] = kwargs.get("payload")

    async def fake_view(session: object) -> dict[str, object]:
        return {"asr_provider": "openai_compatible"}

    monkeypatch.setattr(admin.audit, "record", fake_audit)
    monkeypatch.setattr(admin, "settings_public_view", fake_view)
    monkeypatch.setattr(admin, "client_ip", lambda request: "127.0.0.1")

    result = await admin.update_platform_settings(
        SettingsUpdate(
            asr_provider="openai_compatible",
            asr_base_url="https://router.sedasanj.ir/",
            asr_api_key='Bearer "router-secret"',
        ),
        None,  # type: ignore[arg-type]
        type("S", (), {"id": uuid4()})(),  # type: ignore[arg-type]
        FakeSession(),  # type: ignore[arg-type]
    )

    saved = {row.key: row.value for row in added}
    assert saved == {
        "asr_provider": "openai_compatible",
        "asr_base_url": "https://router.sedasanj.ir",
        "asr_api_key": "router-secret",
    }
    assert seen["audit"] == {
        "asr_provider": "openai_compatible",
        "asr_base_url": "https://router.sedasanj.ir",
        "asr_api_key": "••••cret",
    }
    assert result["asr_provider"] == "openai_compatible"


@pytest.mark.asyncio
async def test_settings_update_requires_key_when_switching_to_9router() -> None:
    class FakeSession:
        async def get(self, model: object, key: str) -> None:
            return None

    with pytest.raises(ApiError, match="ASR API key is required"):
        await admin.update_platform_settings(
            SettingsUpdate(
                asr_provider="openai_compatible",
                asr_base_url="https://router.sedasanj.ir",
            ),
            None,  # type: ignore[arg-type]
            type("S", (), {"id": uuid4()})(),  # type: ignore[arg-type]
            FakeSession(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_settings_update_rejects_unknown_prompt_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin, "available_prompt_versions", lambda: frozenset({"known"}))

    with pytest.raises(ApiError, match="unknown prompt version"):
        await admin.update_platform_settings(
            SettingsUpdate(prompt_version="missing"),
            None,
            None,
            None,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_settings_update_accepts_custom_model_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: dict[str, PlatformSetting] = {}

    class FakeSession:
        async def get(self, model: object, key: str) -> PlatformSetting | None:
            return saved.get(key)

        def add(self, row: PlatformSetting) -> None:
            saved[row.key] = row

        async def flush(self) -> None:
            pass

    async def fake_audit(*args: object, **kwargs: object) -> None:
        pass

    async def fake_view(session: object) -> dict[str, object]:
        return {key: value.value for key, value in saved.items()}

    monkeypatch.setattr(admin.audit, "record", fake_audit)
    monkeypatch.setattr(admin, "settings_public_view", fake_view)
    monkeypatch.setattr(admin, "client_ip", lambda request: "127.0.0.1")

    result = await admin.update_platform_settings(
        SettingsUpdate(
            asr_model="  custom-asr  ",
            llm_model="  custom-llm  ",
            chat_model="  custom-chat  ",
        ),
        None,  # type: ignore[arg-type]
        type("S", (), {"id": uuid4()})(),  # type: ignore[arg-type]
        FakeSession(),  # type: ignore[arg-type]
    )

    assert result == {
        "asr_model": "custom-asr",
        "llm_model": "custom-llm",
        "chat_model": "custom-chat",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        SettingsUpdate(audio_denoiser_model="unknown"),
        SettingsUpdate(audio_enhancement_model="unknown"),
    ],
)
async def test_settings_update_rejects_unknown_audio_model(
    payload: SettingsUpdate,
) -> None:
    with pytest.raises(ApiError, match="unknown .* model"):
        await admin.update_platform_settings(
            payload,
            None,
            None,
            None,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_llama_client_sends_per_run_model() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"completion_tokens": 1},
            },
        )

    client = LlamaClient(Settings(llama_server_urls="http://llama", llm_model="default-model"))
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await client.complete("system", "user", model="persisted-model")
    finally:
        await client.close()

    assert seen["model"] == "persisted-model"
