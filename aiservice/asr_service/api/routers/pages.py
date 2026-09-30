"""Public health route and browser-based administration pages."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from asr_service.domain.catalog import CATALOG
from asr_service.infrastructure.storage import MODEL_DIR
from asr_service.services.task_queue import QUEUE_LIMIT, queue_depth
from asr_service.services.ingress import UploadCapacityError, ensure_spool_capacity
from asr_service.web.dashboard import render_admin_page

from ..schemas.responses import HealthResponse

router = APIRouter()


@router.get("/live", include_in_schema=False)
async def live():
    return {"status": "ok"}


@router.get("/ready", include_in_schema=False)
async def ready():
    installed = [
        model_id
        for model_id in CATALOG
        if (MODEL_DIR / model_id / ".complete").exists()
    ]
    depth = queue_depth()
    reasons = []
    if not installed:
        reasons.append("no_model_installed")
    if depth >= QUEUE_LIMIT:
        reasons.append("task_queue_full")
    try:
        ensure_spool_capacity(MODEL_DIR.parent / "tasks")
    except UploadCapacityError:
        reasons.append("spool_capacity_low")
    payload = {
        "status": "ready" if not reasons else "degraded",
        "ready": not reasons,
        "reasons": reasons,
        "tasks": {"active": depth, "capacity": QUEUE_LIMIT},
    }
    return JSONResponse(payload, status_code=200 if not reasons else 503)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Check service health",
    description="Returns liveness, installed-model readiness, and persistent queue utilization. This endpoint is public.",
    tags=["System"],
)
async def health():
    """Report service liveness, readiness, and task-queue capacity."""

    installed = [model_id for model_id in CATALOG if (MODEL_DIR / model_id / ".complete").exists()]
    return {
        "status": "ok",
        "ready": bool(installed),
        "installed_models": installed,
        "tasks": {"active": queue_depth(), "capacity": QUEUE_LIMIT},
    }


@router.get(
    "/admin",
    response_class=HTMLResponse,
    summary="Open administration dashboard",
    description="Serves the main Persian administration dashboard.",
    response_description="The Persian administration dashboard HTML document.",
    tags=["Administration UI"],
)
def admin():
    """Serve the main browser-based administration dashboard."""

    return render_admin_page("dashboard")


@router.get(
    "/admin/history",
    response_class=HTMLResponse,
    summary="Open usage history",
    description="Serves the dashboard with the usage-history view selected.",
    response_description="The Persian administration dashboard HTML document.",
    tags=["Administration UI"],
)
def admin_history():
    """Serve the administration dashboard at its usage-history URL."""

    return render_admin_page("usage")


@router.get(
    "/admin/models",
    response_class=HTMLResponse,
    summary="Open model management",
    description="Serves the dashboard with the model-management view selected.",
    response_description="The Persian administration dashboard HTML document.",
    tags=["Administration UI"],
)
def admin_models():
    """Serve the administration dashboard at its model-management URL."""

    return render_admin_page("models")


@router.get(
    "/admin/keys",
    response_class=HTMLResponse,
    summary="Open API key management",
    description="Serves the dedicated API-key management page.",
    response_description="The Persian administration dashboard HTML document.",
    tags=["Administration UI"],
)
def admin_keys():
    """Serve the API-key management page."""

    return render_admin_page("keys")


@router.get(
    "/admin/settings",
    response_class=HTMLResponse,
    summary="Open network settings",
    description="Serves the network settings page.",
    response_description="The Persian administration dashboard HTML document.",
    tags=["Administration UI"],
)
def admin_settings():
    """Serve the network settings page."""

    return render_admin_page("settings")


@router.get(
    "/admin/security-events",
    response_class=HTMLResponse,
    summary="Open rejected-request history",
    description="Serves the network-policy rejection history page.",
    response_description="The Persian administration dashboard HTML document.",
    tags=["Administration UI"],
)
def admin_security_events():
    """Serve the rejected-request history page."""

    return render_admin_page("security")
