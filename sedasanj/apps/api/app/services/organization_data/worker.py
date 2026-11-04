from __future__ import annotations

import asyncio
import logging
import time

from app.config import get_settings
from app.db import dispose_engine
from app.logging import configure_logging
from app.metrics import start_metrics_server
from app.services.organization_data import jobs

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    configure_logging("worker-organization-data", settings.log_level)
    start_metrics_server(settings)
    last_maintenance = float("-inf")
    try:
        while True:
            if time.monotonic() - last_maintenance >= 30:
                last_maintenance = time.monotonic()
                for maintenance in (jobs.schedule_due, jobs.expire_one):
                    try:
                        await maintenance()
                    except Exception as exc:
                        logger.error("organization data maintenance failed: %s", type(exc).__name__)
            try:
                if await jobs.run_one():
                    continue
            except Exception as exc:
                logger.error("organization data worker failed: %s", type(exc).__name__)
            await asyncio.sleep(3)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
