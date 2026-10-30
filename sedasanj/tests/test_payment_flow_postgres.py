"""End-to-end payment flow against a disposable, fully migrated PostgreSQL database.

Run `alembic upgrade head` on a scratch database, then set PAYMENT_TEST_DSN to its asyncpg URL
(the name must contain "scratch" or "test"), then run this file.  Never point it at real data.
"""

from __future__ import annotations

import os
import secrets
from uuid import UUID, uuid4

import pytest

TEST_DSN = os.environ.get("PAYMENT_TEST_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="disposable PostgreSQL DSN not supplied")


@pytest.fixture()
async def tenant(monkeypatch):  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from app import db
    from app.config import get_settings
    from app.models import Tenant

    # Other tests may have cached settings (or a dev .env) pointing elsewhere: never trust that.
    assert TEST_DSN
    database = TEST_DSN.rsplit("/", 1)[-1]
    assert "scratch" in database or "test" in database, "refusing to run on a non-test database"
    monkeypatch.setenv("DATABASE_URL", TEST_DSN)
    monkeypatch.setenv("TENANT_DATABASES_ENABLED", "false")
    get_settings.cache_clear()
    await db.dispose_engine()
    assert get_settings().database_url == TEST_DSN
    tenant_id = uuid4()
    async with db.session_scope(staff=True) as session:
        session.add(Tenant(id=tenant_id, name="pay-test", price_per_minute_toman=2000))
    yield tenant_id
    async with db.session_scope(staff=True) as session:
        for table in (
            "ledger_entries",
            "credit_grants",
            "tenant_balance_cache",
            "invoices",
            "refunds",
            "payment_attempts",
            "order_items",
            "orders",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
            )
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    await db.dispose_engine()
    get_settings.cache_clear()


class FakeGateway:
    """Programmable gateway used instead of a bank."""

    code = "behpardakht"
    label = "fake"
    supports_reverse = True
    needs_settle = True

    def __init__(self, behaviour: dict) -> None:  # type: ignore[type-arg]
        self.behaviour = behaviour
        self.calls: list[str] = []

    def parse_callback(self, params):  # type: ignore[no-untyped-def]
        from app.services.gateways import CallbackInfo

        if params.get("ResCode") != "0":
            return CallbackInfo("canceled", params.get("RefId"), None, None, "17")
        return CallbackInfo(
            "ok",
            params.get("RefId"),
            int(params["SaleOrderId"]),
            self.behaviour.get("callback_amount"),
            None,
            {"SaleReferenceId": "SRI-1"},
        )

    async def verify(self, attempt):  # type: ignore[no-untyped-def]
        from app.services.gateways import GatewayError, Verification

        self.calls.append("verify")
        if self.behaviour.get("verify_error"):
            raise GatewayError("network", "down", retryable=True)
        return Verification(
            True,
            code="0",
            ref_id="SRI-1",
            amount_rial=self.behaviour.get("amount", attempt.amount_rial),
        )

    async def settle(self, attempt):  # type: ignore[no-untyped-def]
        from app.services.gateways import GatewayError

        self.calls.append("settle")
        if self.behaviour.get("settle_error"):
            raise GatewayError("network", "down", retryable=True)
        return True

    async def reverse(self, attempt):  # type: ignore[no-untyped-def]
        self.calls.append("reverse")
        return True


@pytest.fixture()
def fake(monkeypatch):  # type: ignore[no-untyped-def]
    from app.services import gateway_settings, payments

    holder = FakeGateway({})
    state = gateway_settings.GatewayState(
        "behpardakht", True, False, {"terminal_id": "1", "username": "u", "password": "p"}
    )

    async def load_all():  # type: ignore[no-untyped-def]
        return {
            code: gateway_settings.GatewayState(code, False, False, {})
            for code in ("zarinpal", "zibal", "saman")
        } | {"behpardakht": state}

    async def load_one(code):  # type: ignore[no-untyped-def]
        return (await load_all())[code]

    async def request(self_, ctx):  # type: ignore[no-untyped-def]
        from app.services.gateways import PaymentStart, RedirectSpec

        holder.last_context = ctx
        return PaymentStart(
            "REF-" + str(ctx.order_ref),
            RedirectSpec("POST", "https://bank/pay", {"RefId": "x"}),
            {},
        )

    monkeypatch.setattr(gateway_settings, "load_all", load_all)
    monkeypatch.setattr(gateway_settings, "load_one", load_one)
    monkeypatch.setattr(payments, "build_gateway", lambda *a, **k: holder)
    holder.request = lambda ctx: request(None, ctx)  # type: ignore[attr-defined]
    return holder


async def make_order(tenant_id: UUID, minutes: int = 100, price: int = 2000):  # type: ignore[no-untyped-def]
    from app import db
    from app.models import Order, OrderItem

    async with db.session_scope(tenant_id) as session:
        order = Order(
            tenant_id=tenant_id,
            number="CR-T-" + secrets.token_hex(3),
            kind="credit",
            status="draft",
            amount_toman=minutes * price,
            callback_token=secrets.token_urlsafe(32),
            idempotency_key=secrets.token_hex(8),
            customer_name="t",
            customer_email="t@example.com",
            customer_mobile="09120000000",
            invoice_profile={},
        )
        session.add(order)
        await session.flush()
        session.add(
            OrderItem(
                order_id=order.id,
                tenant_id=tenant_id,
                kind="credit",
                description="credit",
                quantity=minutes,
                unit_price_toman=price,
                total_toman=minutes * price,
                metadata_json={},
            )
        )
        return order.id, order.callback_token


async def initiate(tenant_id, order_id):  # type: ignore[no-untyped-def]
    from app import db
    from app.models import Order
    from app.services import payments

    async with db.session_scope(tenant_id) as session:
        order = await session.get(Order, order_id)
        attempt, redirect = await payments.initiate(session, order, "behpardakht")
        return attempt.id, attempt.order_ref, redirect


async def balance(tenant_id):  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from app import db
    from app.models import LedgerEntry, TenantBalanceCache

    async with db.session_scope(tenant_id) as session:
        cache = await session.get(TenantBalanceCache, tenant_id)
        rows = (
            (await session.execute(select(LedgerEntry).where(LedgerEntry.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        return (cache.seconds if cache else 0), len(rows)


async def attempt_state(tenant_id, attempt_id):  # type: ignore[no-untyped-def]
    from app import db
    from app.models import PaymentAttempt

    async with db.session_scope(tenant_id) as session:
        row = await session.get(PaymentAttempt, attempt_id)
        return row.status, row.failure_code, row.settled_at, row.check_count


def callback_params(order_ref: int, **extra: str) -> dict[str, str]:
    return {
        "ResCode": "0",
        "RefId": "REF-" + str(order_ref),
        "SaleOrderId": str(order_ref),
        "SaleReferenceId": "SRI-1",
        **extra,
    }


async def test_successful_payment_credits_minutes_once(tenant, fake):  # type: ignore[no-untyped-def]
    from app.services import payments

    order_id, token = await make_order(tenant, minutes=100)
    attempt_id, order_ref, redirect = await initiate(tenant, order_id)
    assert redirect["method"] == "POST" and redirect["fields"]["RefId"]
    assert f"attempt={attempt_id}" in fake.last_context.callback_url
    assert fake.last_context.amount_rial == 100 * 2000 * 10

    for _ in range(2):  # a repeated bank return must not credit twice
        outcome = await payments.handle_callback(
            "behpardakht",
            callback_params(order_ref),
            token=token,
            attempt_id=attempt_id,
            tenant_hint=tenant,
        )
        assert outcome.result == "paid"
    seconds, ledger_rows = await balance(tenant)
    assert seconds == 100 * 60 and ledger_rows == 1
    status, failure, settled_at, _ = await attempt_state(tenant, attempt_id)
    assert status == "verified" and settled_at is not None and failure is None
    assert fake.calls.count("verify") == 1 and fake.calls.count("settle") == 1


async def test_amount_mismatch_is_rejected_and_reversed(tenant, fake):  # type: ignore[no-untyped-def]
    from app.services import payments

    fake.behaviour["callback_amount"] = 1
    order_id, token = await make_order(tenant)
    attempt_id, order_ref, _ = await initiate(tenant, order_id)
    outcome = await payments.handle_callback(
        "behpardakht",
        callback_params(order_ref),
        token=token,
        attempt_id=attempt_id,
        tenant_hint=tenant,
    )
    assert outcome.result == "failed"
    assert (await balance(tenant))[0] == 0
    assert (await attempt_state(tenant, attempt_id))[:2] == ("failed", "amount_mismatch")
    assert "reverse" in fake.calls and "verify" not in fake.calls


async def test_verified_amount_mismatch_never_credits(tenant, fake):  # type: ignore[no-untyped-def]
    from app.services import payments

    fake.behaviour["amount"] = 5
    order_id, token = await make_order(tenant)
    attempt_id, order_ref, _ = await initiate(tenant, order_id)
    outcome = await payments.handle_callback(
        "behpardakht",
        callback_params(order_ref),
        token=token,
        attempt_id=attempt_id,
        tenant_hint=tenant,
    )
    assert outcome.result == "failed" and (await balance(tenant))[0] == 0
    assert "reverse" in fake.calls


async def test_wrong_token_or_order_ref_is_refused(tenant, fake):  # type: ignore[no-untyped-def]
    from app.errors import ApiError
    from app.services import payments

    order_id, token = await make_order(tenant)
    attempt_id, order_ref, _ = await initiate(tenant, order_id)
    with pytest.raises(ApiError):
        await payments.handle_callback(
            "behpardakht",
            callback_params(order_ref),
            token="x" * 43,
            attempt_id=attempt_id,
            tenant_hint=tenant,
        )
    outcome = await payments.handle_callback(
        "behpardakht",
        callback_params(order_ref + 1),
        token=token,
        attempt_id=attempt_id,
        tenant_hint=tenant,
    )
    assert outcome.result == "failed" and (await balance(tenant))[0] == 0


async def test_user_cancel_keeps_order_payable(tenant, fake):  # type: ignore[no-untyped-def]
    from app.services import payments

    order_id, token = await make_order(tenant)
    attempt_id, order_ref, _ = await initiate(tenant, order_id)
    outcome = await payments.handle_callback(
        "behpardakht",
        {"ResCode": "17", "RefId": "REF-" + str(order_ref)},
        token=token,
        attempt_id=attempt_id,
        tenant_hint=tenant,
    )
    assert outcome.result == "canceled"
    new_attempt, _, _ = await initiate(tenant, order_id)
    assert new_attempt != attempt_id


async def test_network_failure_then_sweeper_completes_payment(tenant, fake):  # type: ignore[no-untyped-def]
    from app.services import payments

    fake.behaviour["verify_error"] = True
    order_id, token = await make_order(tenant, minutes=10)
    attempt_id, order_ref, _ = await initiate(tenant, order_id)
    outcome = await payments.handle_callback(
        "behpardakht",
        callback_params(order_ref),
        token=token,
        attempt_id=attempt_id,
        tenant_hint=tenant,
    )
    assert outcome.result == "pending" and (await balance(tenant))[0] == 0
    assert (await attempt_state(tenant, attempt_id))[0] == "pending_verification"

    fake.behaviour["verify_error"] = False
    counts = await payments.reconcile_pending()
    assert counts["verified"] >= 1
    assert (await balance(tenant))[0] == 10 * 60
    assert (await attempt_state(tenant, attempt_id))[0] == "verified"


async def test_settle_failure_is_retried_by_sweeper(tenant, fake):  # type: ignore[no-untyped-def]
    from app.services import payments

    fake.behaviour["settle_error"] = True
    order_id, token = await make_order(tenant, minutes=10)
    attempt_id, order_ref, _ = await initiate(tenant, order_id)
    outcome = await payments.handle_callback(
        "behpardakht",
        callback_params(order_ref),
        token=token,
        attempt_id=attempt_id,
        tenant_hint=tenant,
    )
    assert outcome.result == "paid"  # money is already credited; settlement is retried
    status, failure, settled_at, _ = await attempt_state(tenant, attempt_id)
    assert status == "verified" and settled_at is None and failure == "settle_network"

    fake.behaviour["settle_error"] = False
    await payments.reconcile_pending()
    assert (await attempt_state(tenant, attempt_id))[2] is not None
    assert (await balance(tenant))[0] == 10 * 60


async def test_second_attempt_after_payment_is_superseded(tenant, fake):  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime, timedelta

    from app import db
    from app.models import Order, PaymentAttempt
    from app.services import payments

    order_id, token = await make_order(tenant, minutes=10)
    first, ref1, _ = await initiate(tenant, order_id)
    # age the first attempt so that a second, distinct attempt is created
    async with db.session_scope(tenant) as session:
        row = await session.get(PaymentAttempt, first)
        row.created_at = datetime.now(UTC) - timedelta(minutes=30)
    second, ref2, _ = await initiate(tenant, order_id)
    assert second != first
    await payments.handle_callback(
        "behpardakht", callback_params(ref1), token=token, attempt_id=first, tenant_hint=tenant
    )
    outcome = await payments.handle_callback(
        "behpardakht", callback_params(ref2), token=token, attempt_id=second, tenant_hint=tenant
    )
    assert outcome.result == "superseded"
    assert (await balance(tenant))[0] == 10 * 60  # credited exactly once
    async with db.session_scope(tenant) as session:
        assert (await session.get(Order, order_id)).status == "paid"
    assert (await attempt_state(tenant, second))[:2] == ("superseded", "order_already_paid")


async def test_gateway_choice_is_validated(tenant, fake):  # type: ignore[no-untyped-def]
    from app import db
    from app.errors import ApiError
    from app.models import Order
    from app.services import payments

    order_id, _ = await make_order(tenant)
    async with db.session_scope(tenant) as session:
        order = await session.get(Order, order_id)
        with pytest.raises(ApiError):
            await payments.initiate(session, order, "zarinpal")  # disabled gateway
        attempt, _ = await payments.initiate(session, order, None)  # single active gateway
        assert attempt.gateway == "behpardakht"


async def test_gateway_reverse_refund_revokes_credit(tenant, fake):  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from app import db
    from app.models import Order, PaymentAttempt
    from app.services import payments

    order_id, token = await make_order(tenant, minutes=10)
    attempt_id, order_ref, _ = await initiate(tenant, order_id)
    await payments.handle_callback(
        "behpardakht",
        callback_params(order_ref),
        token=token,
        attempt_id=attempt_id,
        tenant_hint=tenant,
    )
    staff_id = uuid4()
    async with db.session_scope(staff=True) as session:
        await session.execute(
            text(
                "INSERT INTO staff_users (id, email, password_hash, role) "
                "VALUES (:i, :e, 'x', 'super_admin')"
            ),
            {"i": staff_id, "e": f"{staff_id}@example.com"},
        )
    try:
        async with db.session_scope(tenant) as session:
            order = await session.get(Order, order_id)
            refund = await payments.refund_order(
                session,
                order_id=order_id,
                amount_toman=order.amount_toman,
                method="reverse",
                reason="test reverse",
                idempotency_key=secrets.token_hex(8),
                created_by=staff_id,
                payment_attempt_id=attempt_id,
            )
            assert refund.status == "completed"
            assert order.status == "refunded"
            attempt = await session.get(PaymentAttempt, attempt_id)
            assert attempt.status == "verified"
        assert "reverse" in fake.calls
        assert (await balance(tenant))[0] == 0
    finally:
        async with db.session_scope(staff=True) as session:
            await session.execute(text("DELETE FROM refunds WHERE tenant_id = :t"), {"t": tenant})
            await session.execute(text("DELETE FROM staff_users WHERE id = :i"), {"i": staff_id})
