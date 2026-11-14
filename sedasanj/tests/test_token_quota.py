"""Per-plan LLM token budget against a disposable PostgreSQL database (see plan_helpers)."""

from __future__ import annotations

from plan_helpers import drop_org, make_org, requires_postgres, scratch
from sqlalchemy import update

pytestmark = requires_postgres
__all__ = ["scratch"]


async def _set_limit(org, limit):  # type: ignore[no-untyped-def]
    from app import db
    from app.models import Subscription

    async with db.session_scope(staff=True) as session:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == org.subscription_id)
            .values(llm_monthly_tokens=limit)
        )


async def _grant(org, tokens):  # type: ignore[no-untyped-def]
    from app import db
    from app.models import TokenGrant

    async with db.session_scope(staff=True) as session:
        session.add(
            TokenGrant(
                tenant_id=org.tenant_id,
                source="admin_adjustment",
                total_tokens=tokens,
                remaining_tokens=tokens,
            )
        )


async def _use(org, tokens, task=None):  # type: ignore[no-untyped-def]
    from app.services.ai_usage import record_usage

    await record_usage(
        {"prompt_tokens": tokens, "completion_tokens": 0},
        provider="aiservice",
        model="m",
        feature="analysis",
        provider_task_id=f"{task}-{org.tenant_id}" if task else None,
        tenant_id=org.tenant_id,
    )


async def _budget(org):  # type: ignore[no-untyped-def]
    from app import db
    from app.services import token_quota

    async with db.session_scope(org.tenant_id) as session:
        return await token_quota.budget(session, org.tenant_id)


async def test_no_limit_means_unlimited_and_never_blocks(scratch: None) -> None:
    from app import db
    from app.services import token_quota

    org = await make_org("bronze")
    try:
        await _use(org, 10_000_000)
        async with db.session_scope(org.tenant_id) as session:
            result = await token_quota.require_budget(session, org.tenant_id)
        assert result.unlimited and result.remaining is None
    finally:
        await drop_org(org)


async def test_usage_counts_exactly_and_exhaustion_blocks_new_work(scratch: None) -> None:
    import pytest

    from app import db
    from app.errors import ApiError
    from app.services import token_quota

    org = await make_org("bronze")
    try:
        await _set_limit(org, 1000)
        await _use(org, 600, "t1")
        await _use(org, 600, "t1")  # the same provider task is never counted twice
        state = await _budget(org)
        assert (state.used, state.plan_remaining, state.remaining) == (600, 400, 400)
        await _use(org, 400, "t2")
        async with db.session_scope(org.tenant_id) as session:
            with pytest.raises(ApiError) as caught:
                await token_quota.require_budget(session, org.tenant_id)
        assert caught.value.code == "token_quota_exceeded"
    finally:
        await drop_org(org)


async def test_overflow_is_paid_from_topup_tokens(scratch: None) -> None:
    org = await make_org("bronze")
    try:
        await _set_limit(org, 1000)
        await _grant(org, 500)
        await _use(org, 1200, "a")  # 1000 from the plan, 200 from the top-up
        state = await _budget(org)
        assert state.plan_remaining == 0 and state.topup_remaining == 300
        assert state.remaining == 300
        await _use(org, 300, "b")
        state = await _budget(org)
        assert state.remaining == 0
    finally:
        await drop_org(org)


async def test_unavailable_usage_is_reported_not_counted_as_zero(scratch: None) -> None:
    from app.services.ai_usage import record_usage

    org = await make_org("bronze")
    try:
        await _set_limit(org, 1000)
        await record_usage(
            None,
            provider="9router",
            model="m",
            feature="analysis",
            provider_task_id=f"x-{org.tenant_id}",
            tenant_id=org.tenant_id,
        )
        state = await _budget(org)
        assert state.used == 0 and state.unavailable_events == 1
    finally:
        await drop_org(org)


async def test_admin_token_grant_is_idempotent_and_unblocks_work(scratch: None) -> None:
    from types import SimpleNamespace

    from plan_helpers import request

    from app import db
    from app.routers.admin import TokenGrantCreate, create_token_grant

    org = await make_org("bronze")
    try:
        await _set_limit(org, 100)
        await _use(org, 100, "full")
        assert (await _budget(org)).remaining == 0
        payload = TokenGrantCreate(tokens=5000, note="test", idempotency_key="grant-1")
        async with db.session_scope(staff=True) as session:
            first = await create_token_grant(
                org.tenant_id, payload, request(), SimpleNamespace(id=None), session
            )
        async with db.session_scope(staff=True) as session:
            again = await create_token_grant(
                org.tenant_id, payload, request(), SimpleNamespace(id=None), session
            )
        assert first["grant_id"] == again["grant_id"]
        assert (await _budget(org)).remaining == 5000
    finally:
        await drop_org(org)


async def test_subscription_endpoint_reports_the_token_meter(scratch: None) -> None:
    from app import db
    from app.routers.commerce import get_subscription

    org = await make_org("bronze")
    try:
        await _set_limit(org, 1000)
        await _use(org, 250, "meter")
        async with db.session_scope(org.tenant_id) as session:
            out = await get_subscription(org.principal, session)
        assert out["llm_tokens_limit"] == 1000 and out["llm_tokens_used"] == 250
        assert out["llm_tokens_remaining"] == 750 and out["llm_tokens_unlimited"] is False
    finally:
        await drop_org(org)


async def test_reprocessing_is_gated_by_subscription_and_tokens(scratch) -> None:  # type: ignore[no-untyped-def]
    import pytest

    from app import db
    from app.errors import ApiError
    from app.services import token_quota

    org = await make_org()
    try:
        await _set_limit(org, 100)
        async with db.session_scope(org.tenant_id) as session:
            await token_quota.require_ai_work(session, org.tenant_id)
        await _use(org, 100, "gate")
        async with db.session_scope(org.tenant_id) as session:
            with pytest.raises(ApiError) as caught:
                await token_quota.require_ai_work(session, org.tenant_id)
        assert caught.value.code == "token_quota_exceeded"
        await _grant(org, 50)
        async with db.session_scope(org.tenant_id) as session:
            await token_quota.require_ai_work(session, org.tenant_id)
    finally:
        await drop_org(org)
