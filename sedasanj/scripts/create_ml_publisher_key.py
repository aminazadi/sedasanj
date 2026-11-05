"""Create the machine API key (scope ml:publish) that GPU servers use to publish ML models.

The key belongs to the platform tenant named by ML_PUBLISHER_TENANT_ID (or --tenant-id) and must
be restricted to the GPU server addresses. The secret is printed once on stdout and never stored
in clear; put it in the GPU server's environment as ML_PUBLISH_API_KEY.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.db import dispose_engine, session_scope  # noqa: E402
from app.models import ApiKey  # noqa: E402
from app.security import generate_api_key  # noqa: E402
from app.services import audit  # noqa: E402
from app.services.api_scopes import ML_PUBLISH_SCOPE, normalize_cidrs  # noqa: E402


async def create(tenant_id: UUID, cidrs: list[str], label: str, expires_days: int) -> str:
    secret, prefix, key_hash = generate_api_key()
    async with session_scope(None, staff=True) as session:
        key = ApiKey(
            tenant_id=tenant_id,
            key_hash=key_hash,
            key_prefix=prefix,
            label=label,
            scopes=[ML_PUBLISH_SCOPE],
            allowed_cidrs=cidrs,
            kind="integration",
            expires_at=datetime.now(UTC) + timedelta(days=expires_days),
        )
        session.add(key)
        await session.flush()
        await audit.record(
            session,
            actor_type="staff",
            tenant_id=tenant_id,
            action="api_key.create_ml_publisher",
            payload={"api_key_id": str(key.id), "allowed_cidrs": cidrs},
        )
    await dispose_engine()
    return secret


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", default=os.environ.get("ML_PUBLISHER_TENANT_ID"))
    parser.add_argument("--cidr", action="append", required=True, help="GPU server address/CIDR")
    parser.add_argument("--label", default="ml-publisher")
    parser.add_argument("--expires-days", type=int, default=365)
    args = parser.parse_args()
    if not args.tenant_id:
        parser.error("--tenant-id or ML_PUBLISHER_TENANT_ID is required")
    secret = asyncio.run(
        create(UUID(args.tenant_id), normalize_cidrs(args.cidr), args.label, args.expires_days)
    )
    print(secret)


if __name__ == "__main__":
    main()
