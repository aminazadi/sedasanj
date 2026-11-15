"""Cafe Bazaar / Myket purchase verification and activation (Postgres, mocked store APIs)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import delete, select
from tests.plan_helpers import requires_postgres, scratch  # noqa: F401
from tests.test_jalase_links_postgres import created, personal  # noqa: F401

from app import db
from app.errors import ApiError
from app.models import Plan, PlanVersion, StorePurchase, StoreSku, Subscription
from app.services import store_billing

pytestmark = requires_postgres

SETTINGS = SimpleNamespace(
    jalase_android_package="app.test.pkg",
    bazaar_client_id="cid",
    bazaar_client_secret="csecret",
    bazaar_refresh_token="rtoken",
    myket_access_token="mtoken",
)


@pytest.fixture(autouse=True)
async def store_rows(scratch: None, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    monkeypatch.setattr(store_billing, "get_settings", lambda: SETTINGS)
    monkeypatch.setattr(store_billing, "_bazaar_token", None)
    async with db.control_session_scope() as session:
        await session.execute(delete(StorePurchase))
        await session.execute(delete(StoreSku))
        session.add(
            StoreSku(store="bazaar", sku="jn_bronze_month", kind="plan", plan_code="jn_bronze")
        )
        session.add(
            StoreSku(store="myket", sku="jn_bronze_month", kind="plan", plan_code="jn_bronze")
        )
    yield
    async with db.control_session_scope() as session:
        await session.execute(delete(StorePurchase))
        await session.execute(delete(StoreSku))


def store_client(payload: str, *, state: int = 0, status: int = 200, seen: list[Any] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path.endswith("/auth/token/"):
            return httpx.Response(200, json={"access_token": "A", "expires_in": 3600})
        if status != 200:
            return httpx.Response(status, json={"error": "not_found"})
        return httpx.Response(200, json={"purchaseState": state, "developerPayload": payload})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def plan_code_of(tenant_id: UUID) -> str:
    async with db.session_scope(staff=True) as session:
        row = (
            (
                await session.execute(
                    select(Subscription)
                    .where(Subscription.tenant_id == tenant_id, Subscription.status == "active")
                    .order_by(Subscription.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        assert row is not None
        version = await session.get(PlanVersion, row.plan_version_id)
        assert version is not None
        plan = await session.get(Plan, version.plan_id)
        assert plan is not None
        return plan.code


@pytest.mark.parametrize("store", ["bazaar", "myket"])
async def test_verified_purchase_activates_the_plan_once(store: str, created: list[UUID]) -> None:  # noqa: F811
    tenant_id, user_id = await personal(created)
    seen: list[Any] = []
    async with store_client(str(tenant_id), seen=seen) as client:
        out = await store_billing.verify_and_grant(
            tenant_id=tenant_id,
            user_id=user_id,
            store=store,
            sku="jn_bronze_month",
            purchase_token="token-123456",
            client=client,
        )
        assert out == {"status": "granted", "kind": "plan", "replayed": False}
        assert await plan_code_of(tenant_id) == "jn_bronze"
        again = await store_billing.verify_and_grant(
            tenant_id=tenant_id,
            user_id=user_id,
            store=store,
            sku="jn_bronze_month",
            purchase_token="token-123456",
            client=client,
        )
        assert again["replayed"] is True
    store_call = seen[-1]
    if store == "myket":
        assert store_call.headers["X-Access-Token"] == "mtoken"
        assert "/purchases/products/jn_bronze_month/tokens/token-123456" in str(store_call.url)
    else:
        assert store_call.headers["Authorization"] == "Bearer A"
        assert "/inapp/jn_bronze_month/purchases/token-123456/" in str(store_call.url)


async def test_a_token_cannot_be_used_by_another_account(created: list[UUID]) -> None:  # noqa: F811
    first = await personal(created)
    second = await personal(created)
    async with store_client(str(first[0])) as client:
        await store_billing.verify_and_grant(
            tenant_id=first[0],
            user_id=first[1],
            store="myket",
            sku="jn_bronze_month",
            purchase_token="shared-token-1",
            client=client,
        )
    async with store_client(str(second[0])) as client:
        with pytest.raises(ApiError) as err:
            await store_billing.verify_and_grant(
                tenant_id=second[0],
                user_id=second[1],
                store="myket",
                sku="jn_bronze_month",
                purchase_token="shared-token-1",
                client=client,
            )
    assert err.value.code == "store_purchase_already_used"


@pytest.mark.parametrize(
    ("payload", "state", "status"),
    [("wrong-payload", 0, 200), ("OWN", 1, 200), ("OWN", 0, 404)],
)
async def test_unconfirmed_purchases_are_rejected_and_can_be_retried(
    payload: str,
    state: int,
    status: int,
    created: list[UUID],  # noqa: F811
) -> None:
    tenant_id, user_id = await personal(created)
    body = str(tenant_id) if payload == "OWN" else payload
    async with store_client(body, state=state, status=status) as client:
        with pytest.raises(ApiError) as err:
            await store_billing.verify_and_grant(
                tenant_id=tenant_id,
                user_id=user_id,
                store="bazaar",
                sku="jn_bronze_month",
                purchase_token="fake-token-12",
                client=client,
            )
    assert err.value.code == "store_purchase_invalid"
    async with db.control_session_scope() as session:
        assert (await session.execute(select(StorePurchase))).first() is None
    assert await plan_code_of(tenant_id) != "jn_bronze"


async def test_unknown_sku_and_unreachable_store(
    created: list[UUID],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, user_id = await personal(created)
    with pytest.raises(ApiError) as unknown:
        await store_billing.verify_and_grant(
            tenant_id=tenant_id,
            user_id=user_id,
            store="myket",
            sku="nope",
            purchase_token="token-123456",
        )
    assert unknown.value.code == "store_purchase_invalid"
    monkeypatch.setattr(
        store_billing,
        "get_settings",
        lambda: SimpleNamespace(**{**vars(SETTINGS), "myket_access_token": None}),
    )
    with pytest.raises(ApiError) as down:
        await store_billing.verify_and_grant(
            tenant_id=tenant_id,
            user_id=user_id,
            store="myket",
            sku="jn_bronze_month",
            purchase_token="token-123456",
        )
    assert down.value.code == "store_verify_unavailable"


async def test_a_verified_token_pack_adds_tokens(created: list[UUID]) -> None:  # noqa: F811
    from app.models import TokenPackage
    from app.services import token_quota

    tenant_id, user_id = await personal(created)
    async with db.control_session_scope() as session:
        pack = TokenPackage(
            name="بستهٔ آزمایشی", tokens=120_000, price_toman=50_000, product="jalase_negar"
        )
        session.add(pack)
        await session.flush()
        pack_id = pack.id
        session.add(StoreSku(store="myket", sku="jn_pack_small", kind="pack", package_id=pack_id))
    try:
        async with db.session_scope(tenant_id) as session:
            before = (await token_quota.budget(session, tenant_id)).topup_remaining
        async with store_client(str(tenant_id)) as client:
            out = await store_billing.verify_and_grant(
                tenant_id=tenant_id,
                user_id=user_id,
                store="myket",
                sku="jn_pack_small",
                purchase_token="pack-token-12",
                client=client,
            )
        assert out["kind"] == "pack"
        async with db.session_scope(tenant_id) as session:
            after = (await token_quota.budget(session, tenant_id)).topup_remaining
        assert after - before == 120_000
    finally:
        async with db.control_session_scope() as session:
            await session.execute(delete(StorePurchase))
            await session.execute(delete(StoreSku))
            await session.execute(delete(TokenPackage).where(TokenPackage.id == pack_id))
