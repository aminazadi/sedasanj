"""Personal Jalase-Negar accounts against a disposable PostgreSQL (PAYMENT_TEST_DSN)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from tests.plan_helpers import request, requires_postgres, scratch  # noqa: F401

from app import db
from app.errors import ApiError
from app.models import ApiKey, PhoneOtp, PlatformSetting, Subscription, Tenant, TrialClaim, User
from app.routers import jalase_negar_app as router
from app.security import hash_refresh_token
from app.services import billing, jalase_accounts
from app.services.phone_identity import mobile_accounts
from app.services.signup import create_account

pytestmark = requires_postgres

TENANT_TABLES = (
    "api_keys",
    "audit_events",
    "ledger_entries",
    "credit_grants",
    "tenant_balance_cache",
    "trial_claims",
    "subscriptions",
    "users",
)


def new_mobile() -> str:
    return "09" + str(uuid4().int)[:9]


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(router.ratelimit, "enforce", allow)


@pytest.fixture()
async def created(scratch: None) -> AsyncIterator[list[UUID]]:  # noqa: F811
    tenants: list[UUID] = []
    yield tenants
    async with db.session_scope(staff=True) as session:
        # The scratch role is a superuser: skip the primary-admin delete guard for cleanup only.
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            text("DELETE FROM platform_settings WHERE key = 'jalase_standalone_enabled'")
        )
        for tenant_id in tenants:
            for table in TENANT_TABLES:
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
                )
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


async def personal(
    mobile: str, created: list[UUID], name: str | None = None
) -> tuple[Tenant, User]:
    async with db.session_scope(staff=True) as session:
        tenant, user = await jalase_accounts.create_personal_account(
            session, mobile=mobile, display_name=name, ip="127.0.0.1"
        )
        created.append(tenant.id)
        session.expunge_all()
        return tenant, user


async def test_personal_account_is_free_active_and_funded(created: list[UUID]) -> None:
    mobile = new_mobile()
    tenant, user = await personal(mobile, created, "سارا")
    assert tenant.product == "jalase_negar" and tenant.signup_channel == "jalase_app"
    assert user.signup_channel == "jalase_app" and user.role == "org_admin"
    assert mobile not in tenant.name  # only the masked number is stored in the name
    async with db.session_scope(tenant.id) as session:
        sub = (
            await session.execute(select(Subscription).where(Subscription.tenant_id == tenant.id))
        ).scalar_one()
        assert sub.status == "active" and sub.billing_period == "monthly"
        assert sub.period_end.year == 9999
        assert (await billing.get_balance(session, tenant.id)).seconds == 60 * 60


async def test_accounts_are_visible_only_to_their_own_product(created: list[UUID]) -> None:
    mobile = new_mobile()
    await personal(mobile, created)
    async with db.session_scope(staff=True) as session:
        assert await mobile_accounts(session, mobile) == []  # SedaSanj login ignores them
        assert len(await mobile_accounts(session, mobile, product="jalase_negar")) == 1
        assert len(await mobile_accounts(session, mobile, product=None)) == 1


async def test_sedasanj_signup_cannot_use_the_jalase_plan(created: list[UUID]) -> None:
    async with db.session_scope(staff=True) as session:
        with pytest.raises(ApiError) as caught:
            await create_account(
                session,
                mobile=new_mobile(),
                email=f"{uuid4().hex}@example.com",
                organization_name="Org",
                manager_name="Mgr",
                password="x" * 12,
                plan_code="jn_free",
                ip=None,
            )
        assert caught.value.code == "not_found"


async def test_a_claimed_sedasanj_demo_does_not_block_jalase_signup(created: list[UUID]) -> None:
    mobile = new_mobile()
    async with db.session_scope(staff=True) as session:
        tenant, _ = await create_account(
            session,
            mobile=mobile,
            email=f"{uuid4().hex}@example.com",
            organization_name="Demo Org",
            manager_name="Mgr",
            password="x" * 12,
            plan_code="demo",
            ip=None,
        )
        created.append(tenant.id)
        assert tenant.product == "sedasanj"
    mine, _user = await personal(mobile, created)
    assert mine.id != tenant.id
    async with db.session_scope(staff=True) as session:
        claims = (
            (await session.execute(select(TrialClaim).where(TrialClaim.mobile == mobile)))
            .scalars()
            .all()
        )
        assert len(claims) == 1  # only the SedaSanj demo claimed it


async def test_oldest_device_is_signed_out_at_the_limit(
    created: list[UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("MEETING_TOKEN_LIMIT", "2")
    get_settings.cache_clear()
    _, user = await personal(new_mobile(), created)
    for index in range(3):  # one transaction per login, as in production
        async with db.session_scope(staff=True) as session:
            await jalase_accounts.issue_device_key(
                session,
                user=user,
                device_name=f"d{index}",
                platform="android",
                app_version=None,
                ip=None,
            )
    async with db.session_scope(staff=True) as session:
        keys = (
            (
                await session.execute(
                    select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at)
                )
            )
            .scalars()
            .all()
        )
        assert [key.revoked_at is None for key in keys] == [False, True, True]
    get_settings.cache_clear()


async def enable_flag() -> None:
    async with db.session_scope(staff=True) as session:
        await session.merge(PlatformSetting(key="jalase_standalone_enabled", value="true"))


async def grant_for(mobile: str) -> str:
    token = uuid4().hex + uuid4().hex
    async with db.session_scope(staff=True) as session:
        session.add(
            PhoneOtp(
                mobile=mobile,
                code_hash="x",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
                verified_at=datetime.now(UTC),
                grant_hash=hash_refresh_token(token),
                grant_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
    return token


async def test_complete_is_closed_until_the_flag_is_on(created: list[UUID]) -> None:
    token = await grant_for(new_mobile())
    with pytest.raises(ApiError) as caught:
        await router.auth_complete(
            router.AuthComplete(verified_token=token, device_name="Pixel", platform="android"),
            request(),
        )
    assert caught.value.code == "jalase_signup_disabled"


async def test_complete_signs_up_then_logs_in_to_the_same_account(created: list[UUID]) -> None:
    await enable_flag()
    mobile = new_mobile()
    first = await router.auth_complete(
        router.AuthComplete(
            verified_token=await grant_for(mobile),
            display_name="رضا",
            device_name="Pixel",
            platform="android",
        ),
        request(),
    )
    assert first["created"] is True
    async with db.session_scope(staff=True) as session:
        account = (await mobile_accounts(session, mobile, product="jalase_negar"))[0]
        created.append(account[1].id)
    second = await router.auth_complete(
        router.AuthComplete(
            verified_token=await grant_for(mobile), device_name="Mac", platform="macos"
        ),
        request(),
    )
    assert second["created"] is False
    async with db.session_scope(staff=True) as session:
        assert len(await mobile_accounts(session, mobile, product="jalase_negar")) == 1


# ----------------------------------------------------------------------------- admin users

from types import SimpleNamespace  # noqa: E402

from app.routers import admin_users  # noqa: E402


def staff() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4())


async def test_admin_list_filters_by_product_and_channel(created: list[UUID]) -> None:
    mobile = new_mobile()
    mine, _ = await personal(mobile, created, "فیلتر ")
    async with db.session_scope(staff=True) as session:
        sed, _ = await create_account(
            session,
            mobile=new_mobile(),
            email=f"{uuid4().hex}@example.com",
            organization_name="SedaOrg",
            manager_name="Mgr",
            password="x" * 12,
            plan_code="demo",
            ip=None,
        )
        created.append(sed.id)
    async with db.session_scope(staff=True) as session:
        found = await admin_users.list_users(
            staff(),
            session,
            admin_users.UserFilters(product="jalase_negar", signup_channel="jalase_app", q=mobile),
        )
        assert found["total"] == 1
        item = found["items"][0]
        assert item["tenant_id"] == str(mine.id) and item["plan_code"] == "jn_free"
        assert item["subscription_status"] == "active"
        sed_only = await admin_users.list_users(
            staff(), session, admin_users.UserFilters(product="sedasanj", q="SedaOrg")
        )
        assert [row["tenant_id"] for row in sed_only["items"]] == [str(sed.id)]
        by_plan = await admin_users.list_users(
            staff(), session, admin_users.UserFilters(plan_code="jn_free", q=mobile)
        )
        assert by_plan["total"] == 1


async def test_admin_export_is_csv_with_neutralised_cells(created: list[UUID]) -> None:
    mobile = new_mobile()
    await personal(mobile, created, "=HYPERLINK(1)")
    async with db.session_scope(staff=True) as session:
        response = await admin_users.export_users(
            SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
            staff(),
            session,
            admin_users.UserFilters(product="jalase_negar", q=mobile),
            "csv",
        )
    text_body = response.body.decode("utf-8-sig")
    assert mobile in text_body and "جلسه‌نگار" in text_body
    assert "'=HYPERLINK" in text_body  # a formula prefix never reaches the spreadsheet


async def test_bulk_is_a_dry_run_first_and_never_touches_sedasanj_orgs(
    created: list[UUID],
) -> None:
    mobile = new_mobile()
    mine, _ = await personal(mobile, created)
    async with db.session_scope(staff=True) as session:
        sed, _ = await create_account(
            session,
            mobile=new_mobile(),
            email=f"{uuid4().hex}@example.com",
            organization_name="BulkSedaOrg",
            manager_name="Mgr",
            password="x" * 12,
            plan_code="demo",
            ip=None,
        )
        created.append(sed.id)
    req = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    async with db.session_scope(staff=True) as session:
        preview = await admin_users.bulk_action(
            admin_users.BulkRequest(
                action="suspend", filters=admin_users.UserFilters(q="BulkSeda")
            ),
            req,
            staff(),
            session,
        )
        assert preview == {"dry_run": True, "count": 0, "action": "suspend"}  # Seda org excluded
    async with db.session_scope(staff=True) as session:
        preview = await admin_users.bulk_action(
            admin_users.BulkRequest(action="suspend", filters=admin_users.UserFilters(q=mobile)),
            req,
            staff(),
            session,
        )
        assert preview["count"] == 1
        ran = await admin_users.bulk_action(
            admin_users.BulkRequest(
                action="suspend", filters=admin_users.UserFilters(q=mobile), dry_run=False
            ),
            req,
            staff(),
            session,
        )
        assert ran["done"] == 1
    async with db.session_scope(staff=True) as session:
        assert (await session.get(Tenant, mine.id)).status == "suspended"
        assert (await session.get(Tenant, sed.id)).status == "active"


async def test_bulk_credit_and_sms_guards(created: list[UUID]) -> None:
    mobile = new_mobile()
    mine, _ = await personal(mobile, created)
    req = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    async with db.session_scope(staff=True) as session:
        with pytest.raises(ApiError) as no_minutes:
            await admin_users.bulk_action(
                admin_users.BulkRequest(action="grant_credit"), req, staff(), session
            )
        assert no_minutes.value.code == "invalid_request"
        with pytest.raises(ApiError) as no_template:
            await admin_users.bulk_action(
                admin_users.BulkRequest(action="sms", message="سلام"), req, staff(), session
            )
        assert no_template.value.code == "sms_template_missing"
        await admin_users.bulk_action(
            admin_users.BulkRequest(
                action="grant_credit",
                minutes=30,
                filters=admin_users.UserFilters(q=mobile),
                dry_run=False,
            ),
            req,
            staff(),
            session,
        )
    async with db.session_scope(mine.id) as session:
        assert (await billing.get_balance(session, mine.id)).seconds == 60 * 60 + 30 * 60
