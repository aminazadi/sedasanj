from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.routers.commerce import CheckoutCreate, PlanVersionCreate, _plan_out


def version_payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
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


def test_monthly_fields_are_not_part_of_plan_contract() -> None:
    with pytest.raises(ValidationError):
        PlanVersionCreate(**version_payload(monthly_price_toman=100_000))


def test_checkout_rejects_monthly_billing_period() -> None:
    with pytest.raises(ValidationError):
        CheckoutCreate(
            plan_code="bronze",
            billing_period="monthly",
            customer_name="Admin",
            customer_email="admin@example.com",
            customer_mobile="09123456789",
            invoice_profile={},
        )


def test_extra_operator_capability_requires_annual_price() -> None:
    with pytest.raises(ValidationError):
        PlanVersionCreate(**version_payload(allows_extra_operators=True))
    PlanVersionCreate(
        **version_payload(allows_extra_operators=True, extra_operator_annual_toman=100_000)
    )


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
        extra_operator_annual_toman=None,
        trial_days=None,
    )
    output = _plan_out(plan, version)
    assert output["status"] == "draft"
    assert output["assistant_model"] == "model-a"
