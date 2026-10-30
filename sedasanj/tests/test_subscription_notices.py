"""Subscription notices are chosen by state and sent once per period (WP-6)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from plan_helpers import drop_org, make_org, requires_postgres, scratch
from sqlalchemy import text

pytestmark = requires_postgres
__all__ = ["scratch"]


class Mailbox:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = fail

    async def __call__(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            raise RuntimeError("smtp down")
        self.sent.append((to, subject, body))


async def _cleanup(org: Any) -> None:
    from app import db

    async with db.session_scope(staff=True) as session:
        await session.execute(
            text("DELETE FROM notification_log WHERE tenant_id = :t"), {"t": org.tenant_id}
        )
    await drop_org(org)


async def test_renewal_notice_is_sent_once(scratch: None) -> None:
    from app.services import subscription_notices

    org = await make_org("bronze", end_days=6)
    try:
        box = Mailbox()
        now = datetime.now(UTC)
        first = await subscription_notices.send_tenant_notices(org.tenant_id, now, box)
        second = await subscription_notices.send_tenant_notices(org.tenant_id, now, box)
        assert (first, second) == (1, 0)
        assert len(box.sent) == 1 and "تمدید" in box.sent[0][2]
    finally:
        await _cleanup(org)


async def test_notice_kinds_follow_the_state(scratch: None) -> None:
    from app import db
    from app.services import subscription_notices

    cases = {
        "trial_ending": await make_org("demo", status="trialing", period="trial", end_days=1),
        "grace_started": await make_org("bronze", end_days=-1),
        "none": await make_org("bronze", end_days=200),
    }
    try:
        now = datetime.now(UTC)
        async with db.session_scope(staff=True) as session:
            for expected, org in cases.items():
                found = await subscription_notices.due_notices(session, org.tenant_id, now)
                kinds = {notice.kind for notice in found}
                assert kinds == (set() if expected == "none" else {expected}), expected
    finally:
        for org in cases.values():
            await _cleanup(org)


async def test_failed_send_is_retried_then_given_up(scratch: None) -> None:
    from app.services import subscription_notices

    org = await make_org("bronze", end_days=1)
    try:
        now = datetime.now(UTC)
        broken = Mailbox(fail=True)
        for _ in range(subscription_notices.MAX_ATTEMPTS + 2):
            await subscription_notices.send_tenant_notices(org.tenant_id, now, broken)
        healthy = Mailbox()
        assert await subscription_notices.send_tenant_notices(org.tenant_id, now, healthy) == 0
        assert healthy.sent == []
    finally:
        await _cleanup(org)


async def test_expired_unpaid_signup_gets_no_notice(scratch: None) -> None:
    from app import db
    from app.services import subscription_notices

    org = await make_org("bronze", status="expired", end_days=-1)
    try:
        async with db.session_scope(staff=True) as session:
            notices = await subscription_notices.due_notices(
                session, org.tenant_id, datetime.now(UTC)
            )
        assert notices == []
    finally:
        await _cleanup(org)
