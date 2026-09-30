"""ASGI entrypoint kept stable for ``uvicorn app:app`` deployments."""

from asr_service.api.application import app
from asr_service.api.dependencies import authorize
from asr_service.api.routers.models import install, known, model_status, models, pause, resume
from asr_service.api.routers.pages import admin, admin_history, admin_models, health
from asr_service.api.routers.proxy import get_proxy, proxy_test, put_proxy
from asr_service.api.routers.tasks import (
    accepted,
    cancel_task,
    idempotency,
    subtitles,
    task_result,
    task_status,
    text_process,
    transcription,
    ts,
)
from asr_service.api.schemas.requests import ProxyConfigRequest, TextProcessRequest

__all__ = ["app"]
