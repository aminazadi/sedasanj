from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.deps import Principal
from app.errors import ApiError
from app.models import User
from app.routers.auth import get_user


@pytest.mark.parametrize("same_tenant", [True, False])
async def test_read_member_for_editor(same_tenant: bool) -> None:
    tenant_id = uuid4()
    principal = Principal("user", uuid4(), tenant_id, "org_admin")
    member = User(
        id=uuid4(),
        tenant_id=tenant_id if same_tenant else uuid4(),
        email="member@example.com",
        role="operator",
        extension="201",
        display_name="Member",
        created_at=datetime.now(UTC),
    )
    session = AsyncMock()
    session.get.return_value = member
    if not same_tenant:
        with pytest.raises(ApiError) as exc:
            await get_user(member.id, session, principal)
        assert exc.value.code == "not_found"
        return

    result = await get_user(member.id, session, principal)
    assert result.id == member.id
    assert result.display_name == "Member"
    assert result.extension == "201"
