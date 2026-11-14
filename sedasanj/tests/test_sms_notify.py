"""SMS.ir template sends: provider contract, parameter mapping, thresholds, queue idempotency."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from plan_helpers import requires_postgres, scratch
from sqlalchemy import delete

from app.services import sms_notify, smsir, usage_alerts
from app.services.demo_settings import DemoSettings

__all__ = ["scratch"]

SETTINGS = DemoSettings(smsir_api_key="test-key", smsir_base_url="https://sms.test/v1")


def _client(monkeypatch, handler):  # type: ignore[no-untyped-def]
    real = httpx.AsyncClient

    def factory(**kwargs):  # type: ignore[no-untyped-def]
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(smsir.httpx, "AsyncClient", factory)


async def test_send_template_posts_named_parameters(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": 1})

    _client(monkeypatch, handler)
    await smsir.send_template("09120000000", 123, {"ORG": "الف"}, SETTINGS)
    assert seen["url"] == "https://sms.test/v1/send/verify"
    assert seen["key"] == "test-key"
    assert seen["body"] == {
        "mobile": "09120000000",
        "templateId": 123,
        "parameters": [{"name": "ORG", "value": "الف"}],
    }


@pytest.mark.parametrize(
    ("response", "retryable", "unknown"),
    [
        (httpx.Response(200, json={"status": 0}), False, False),
        (httpx.Response(200, text="not json"), False, False),
        (httpx.Response(400, json={"status": 1}), False, False),
        (httpx.Response(503), True, False),
        (httpx.Response(429), True, False),
    ],
)
async def test_send_template_failures(monkeypatch, response, retryable, unknown) -> None:  # type: ignore[no-untyped-def]
    _client(monkeypatch, lambda request: response)
    with pytest.raises(smsir.SmsDeliveryError) as caught:
        await smsir.send_template("09120000000", 1, {}, SETTINGS)
    assert caught.value.retryable is retryable
    assert caught.value.unknown is unknown


async def test_send_template_timeout_is_unknown_and_secret_free(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    _client(monkeypatch, handler)
    with pytest.raises(smsir.SmsDeliveryError) as caught:
        await smsir.send_template("09120000000", 1, {}, SETTINGS)
    assert caught.value.unknown and not caught.value.retryable
    assert "test-key" not in str(caught.value)


async def test_send_template_requires_api_key() -> None:
    with pytest.raises(smsir.SmsDeliveryError):
        await smsir.send_template("09120000000", 1, {}, DemoSettings(smsir_api_key=""))


def test_levels_are_percentages_of_the_plan() -> None:
    assert usage_alerts.level_for(0, 600) is None
    assert usage_alerts.level_for(479, 600) is None
    assert usage_alerts.level_for(480, 600) == "80"
    assert usage_alerts.level_for(569, 600) == "80"
    assert usage_alerts.level_for(570, 600) == "95"
    assert usage_alerts.level_for(600, 600) == "exhausted"
    assert usage_alerts.level_for(10, 0) is None
    assert usage_alerts.level_for(80, 100) == "80"


def test_every_event_maps_to_known_values() -> None:
    from app.routers.sms_templates import SAMPLE_VALUES

    for event in sms_notify.EVENTS.values():
        assert set(event.values) <= set(SAMPLE_VALUES), event.key


def test_build_parameters_maps_provider_names() -> None:
    from types import SimpleNamespace

    template = SimpleNamespace(parameters={"NAME": "ORG", "LEFT": "REMAINING", "X": "MISSING"})
    assert sms_notify.build_parameters(template, {"ORG": "الف", "REMAINING": 5}) == {  # type: ignore[arg-type]
        "NAME": "الف",
        "LEFT": "5",
        "X": "",
    }


@requires_postgres
async def test_enqueue_is_idempotent_and_deliver_is_one_shot(scratch, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app import db
    from app.models import SmsDelivery, SmsTemplate

    key = f"t:{uuid4()}"
    sent: list[tuple[str, int, dict[str, str]]] = []

    async def fake_send(mobile, template_id, parameters, settings):  # type: ignore[no-untyped-def]
        sent.append((mobile, template_id, parameters))

    async def fake_load(session):  # type: ignore[no-untyped-def]
        return SETTINGS

    monkeypatch.setattr(sms_notify, "send_template", fake_send)
    monkeypatch.setattr(sms_notify.demo_settings, "load", fake_load)
    try:
        async with db.control_session_scope() as session:
            await session.execute(delete(SmsDelivery))
            await session.merge(
                SmsTemplate(
                    event_key="welcome", template_id=77, parameters={"NAME": "ORG"}, enabled=True
                )
            )
        assert await sms_notify.enqueue("welcome", "0912 000 0000", {"ORG": "الف"}, key)
        assert not await sms_notify.enqueue("welcome", "09120000000", {"ORG": "الف"}, key)
        assert not await sms_notify.enqueue("nope", "09120000000", {}, key + "x")
        assert not await sms_notify.enqueue("welcome", "123", {}, key + "y")  # bad mobile
        counts = await sms_notify.deliver_pending()
        assert counts["sent"] == 1
        assert sent == [("09120000000", 77, {"NAME": "الف"})]
        assert (await sms_notify.deliver_pending())["sent"] == 0  # nothing is sent twice

        # a disabled template never reaches the provider
        async with db.control_session_scope() as session:
            template = await session.get(SmsTemplate, "welcome")
            template.enabled = False
        await sms_notify.enqueue("welcome", "09120000001", {}, key + "z")
        assert (await sms_notify.deliver_pending())["skipped"] == 1
        assert len(sent) == 1
    finally:
        async with db.control_session_scope() as session:
            await session.execute(delete(SmsDelivery))
            await session.execute(delete(SmsTemplate))


@requires_postgres
async def test_timeout_is_marked_unknown_and_never_retried(scratch, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app import db
    from app.models import SmsDelivery, SmsTemplate

    calls = 0

    async def slow(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        raise smsir.SmsDeliveryError("provider timeout", unknown=True)

    async def fake_load(session):  # type: ignore[no-untyped-def]
        return SETTINGS

    monkeypatch.setattr(sms_notify, "send_template", slow)
    monkeypatch.setattr(sms_notify.demo_settings, "load", fake_load)
    try:
        async with db.control_session_scope() as session:
            await session.execute(delete(SmsDelivery))
            await session.merge(SmsTemplate(event_key="welcome", template_id=5, enabled=True))
        await sms_notify.enqueue("welcome", "09120000002", {}, f"u:{uuid4()}")
        assert (await sms_notify.deliver_pending())["unknown"] == 1
        await sms_notify.deliver_pending()
        assert calls == 1
    finally:
        async with db.control_session_scope() as session:
            await session.execute(delete(SmsDelivery))
            await session.execute(delete(SmsTemplate))


@requires_postgres
async def test_token_alerts_fire_once_per_level_and_window(scratch) -> None:  # type: ignore[no-untyped-def]
    from plan_helpers import drop_org, make_org
    from sqlalchemy import select, update

    from app import db
    from app.models import SmsDelivery, Subscription
    from app.services.ai_usage import record_usage

    org = await make_org()
    try:
        async with db.session_scope(staff=True) as session:
            await session.execute(
                update(Subscription)
                .where(Subscription.id == org.subscription_id)
                .values(llm_monthly_tokens=1000)
            )

        async def use(tokens: int, task: str) -> None:
            await record_usage(
                {"prompt_tokens": tokens, "completion_tokens": 0},
                provider="aiservice",
                model="m",
                feature="analysis",
                provider_task_id=f"{task}-{org.tenant_id}",
                tenant_id=org.tenant_id,
            )

        async def events() -> list[str]:
            async with db.control_session_scope() as session:
                rows = await session.execute(
                    select(SmsDelivery.event_key).where(SmsDelivery.tenant_id == org.tenant_id)
                )
                return sorted(rows.scalars())

        assert await usage_alerts.check_tenant(org.tenant_id) == 0
        await use(800, "a")
        assert await usage_alerts.check_tenant(org.tenant_id) == 1
        assert await usage_alerts.check_tenant(org.tenant_id) == 0  # same level, same window
        await use(160, "b")
        await usage_alerts.check_tenant(org.tenant_id)
        await use(100, "c")
        await usage_alerts.check_tenant(org.tenant_id)
        assert await events() == ["tokens_80", "tokens_95", "tokens_exhausted"]
    finally:
        async with db.control_session_scope() as session:
            await session.execute(delete(SmsDelivery).where(SmsDelivery.tenant_id == org.tenant_id))
        await drop_org(org)
