"""Application startup and shutdown lifecycle."""

from contextlib import asynccontextmanager

from asr_service.infrastructure.storage import init_db, rows
from asr_service.domain.catalog import load_custom_models
from asr_service.services.downloader import manager as download_manager
from asr_service.services.task_queue import manager as task_manager


@asynccontextmanager
async def lifespan(_):
    """Initialize persistence, resume model downloads, and run task workers."""

    init_db()
    load_custom_models()
    for saved in rows(
        "SELECT model_id FROM model_state WHERE status IN ('queued','downloading','preparing','converting','validating')"
    ):
        download_manager.install(saved["model_id"])
    task_manager.start()
    yield
    task_manager.stop()
