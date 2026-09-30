from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.routers.commerce import PlanVersionCreate, _plan_out
from app.services.payments import ZarinpalGateway


def version_payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "monthly_price_toman": 1_000_000,
        "annual_price_toman": 10_000_000,
        "base_operators": 2,
        "intro_minutes": 100,
        "overage_price_per_minute_toman": 2_000,
        "assistant_tier": "simple",
        "assistant_monthly_messages": 50,
        "assistant_source_limit": 8,
        "allows_extra_operators": False,
    }
    values.update(overrides)
    return values


def test_extra_operator_prices_require_capability() -> None:
    with pytest.raises(ValidationError):
        PlanVersionCreate(**version_payload(extra_operator_monthly_toman=100_000))


def test_extra_operator_capability_requires_monthly_price() -> None:
    with pytest.raises(ValidationError):
        PlanVersionCreate(**version_payload(allows_extra_operators=True))


def test_plan_output_includes_lifecycle_and_assistant_model() -> None:
    plan = SimpleNamespace(id="plan", code="gold", name="طلایی")
    version = SimpleNamespace(
        id="version",
        version=3,
        status="draft",
        effective_at=None,
        published_at=None,
        retired_at=None,
        assistant_model="model-a",
        **version_payload(),
        extra_operator_monthly_toman=None,
        extra_operator_annual_toman=None,
        trial_days=None,
    )
    output = _plan_out(plan, version)
    assert output["status"] == "draft"
    assert output["assistant_model"] == "model-a"


@pytest.mark.asyncio
async def test_gateway_query_uses_inquiry_without_verifying() -> None:
    gateway = object.__new__(ZarinpalGateway)
    gateway.merchant_id = "merchant"
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_post(action: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((action, payload))
        return {"data": {"status": "PAID", "code": 100}}

    gateway._post = fake_post  # type: ignore[method-assign]
    result = await gateway.query(amount_rial=10_000, authority="A-test")
    assert result.success is True
    assert calls == [("inquiry", {"merchant_id": "merchant", "authority": "A-test"})]
