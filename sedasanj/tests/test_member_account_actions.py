from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import jwt
import pytest

from app.config import get_settings
from app.errors import ApiError
from app.models import RefreshToken, Tenant, User
from app.security import JWT_ALGORITHM, hash_refresh_token
from app.services import member_account_actions as actions


@pytest.fixture
def account():
    tenant_id = uuid4()
    user = User(id=uuid4(), tenant_id=tenant_id, email="old@example.com", role="operator")
    admin = User(id=uuid4(), tenant_id=tenant_id, role="org_admin")
    tenant = Tenant(id=tenant_id, status="active")
    session = AsyncMock()
    session.get.side_effect = lambda model, key, **_: {
        (User, user.id): user,
        (User, admin.id): admin,
        (Tenant, tenant.id): tenant,
    }.get((model, key))
    return SimpleNamespace(session=session, user=user, admin=admin)


async def test_account_link_is_distinct_from_refresh_and_single_use(account, monkeypatch):
    delivered = {}

    def send(_settings, recipient, action, token):
        delivered.update(recipient=recipient, action=action, token=token)

    monkeypatch.setattr(actions, "_send", send)
    account.session.add = added = Mock()
    await actions.issue(account.session, account.user, account.admin.id, "email", "new@example.com")
    stored = added.call_args.args[0]
    assert isinstance(stored, RefreshToken)
    token = delivered["token"]
    assert account.user.email == "old@example.com"
    assert delivered["recipient"] == "new@example.com"
    assert stored.token_hash != hash_refresh_token(token)
    account.session.scalar.side_effect = lambda *_: stored if stored.revoked_at is None else None

    with pytest.raises(ApiError) as wrong_purpose:
        await actions.consume(account.session, "password", token)
    assert wrong_purpose.value.code == "member_account_link_invalid"
    user, actor_id, recipient = await actions.consume(account.session, "email", token)
    assert (user.id, actor_id, recipient) == (account.user.id, account.admin.id, "new@example.com")
    assert stored.revoked_at is not None
    with pytest.raises(ApiError, match="پیوند"):
        await actions.consume(account.session, "email", token)


@pytest.mark.parametrize("expired", [True, False])
async def test_reject_expired_link_or_demoted_admin(account, expired):
    if not expired:
        account.admin.role = "viewer"
    token = jwt.encode(
        {
            "typ": "member-account:password:",
            "sub": str(account.user.id),
            "actor_id": str(account.admin.id),
            "email": account.user.email,
            "recipient": account.user.email,
            "exp": datetime.now(UTC) + timedelta(minutes=-1 if expired else 1),
        },
        get_settings().jwt_secret,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(ApiError) as error:
        await actions.consume(account.session, "password", token)
    assert error.value.code == "member_account_link_invalid"
    account.session.scalar.assert_not_awaited()
