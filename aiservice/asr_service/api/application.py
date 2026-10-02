"""FastAPI application assembly and audience-specific ReDoc documents."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.docs import get_redoc_html
from fastapi.openapi.utils import get_openapi

from asr_service.domain.catalog import CATALOG
from asr_service.infrastructure import storage
from asr_service.infrastructure.ninerouter import cached_models, configured_model

from .lifecycle import lifespan
from .admission import IngressAdmissionMiddleware
from .cors import DynamicCORSMiddleware
from .failure_audit import RequestFailureAuditMiddleware
from .routers import analytics, models, ninerouter, openai_compat, pages, proxy, security, tasks

DESCRIPTION = """Persian speech-to-text and text-processing service.

Inference runs asynchronously through a persistent task queue. A request may select one model or an explicitly ordered list; model runs execute sequentially with independent retries, results, and logs. Submit work, poll the returned task URL, and retrieve the result after it succeeds or partially succeeds. Protected operations require `Authorization: Bearer <ASR_API_KEY>`.
"""

TAGS = [
    {"name": "System", "description": "Public service health and readiness."},
    {
        "name": "Transcription",
        "description": "Asynchronous Persian speech recognition.",
    },
    {
        "name": "Text processing",
        "description": "Transcript correction and meeting-minutes generation.",
    },
    {
        "name": "Tasks",
        "description": "Task polling, result retrieval, and cancellation.",
    },
    {
        "name": "Model management",
        "description": "Model catalog, installation, and download lifecycle.",
    },
    {
        "name": "Usage analytics",
        "description": "Administrative parent-request history, ordered per-model execution details and logs, and aggregate metrics.",
    },
    {
        "name": "Download proxy",
        "description": "Proxy configuration for model downloads.",
    },
    {"name": "Administration UI", "description": "Browser-based administration pages."},
]


def installed_model_ids(kind):
    """Return installed catalog identifiers of one inference kind."""

    values = [
        model_id
        for model_id, spec in CATALOG.items()
        if spec.kind == kind and (storage.MODEL_DIR / model_id / ".complete").is_file()
    ]
    remote = [item["id"] for item in cached_models() if item.get("kind") == kind]
    configured = configured_model(kind)
    return list(dict.fromkeys(values + remote + ([configured] if configured else [])))


def document_installed_models(schema):
    """Expose the currently usable model keys in the user OpenAPI document."""

    asr_models = installed_model_ids("asr")
    llm_models = installed_model_ids("llm")

    def keys(values):
        return ", ".join(f"`{value}`" for value in values) or "None"

    schema["info"]["description"] += (
        "\n\n## Currently installed model keys\n\n"
        f"**Speech-to-text (`model`):** {keys(asr_models)}\n\n"
        f"**Text processing (`model` / `models`):** {keys(llm_models)}\n\n"
        "This list is generated from the models available on this server and updates when this document is refreshed."
    )

    components = schema.get("components", {}).get("schemas", {})
    transcription = components.get(
        "Body_transcription_v1_audio_transcriptions_post", {}
    )
    asr_property = transcription.get("properties", {}).get("model")
    if asr_property is not None:
        asr_property["description"] = (
            f"Installed ASR model identifier. Available keys: {keys(asr_models)}."
        )
        if asr_models:
            asr_property["enum"] = asr_models
    asr_models_property = transcription.get("properties", {}).get("models")
    if asr_models_property is not None:
        asr_models_property["description"] = (
            "Ordered installed ASR model identifiers. Repeat the multipart field in execution order. "
            f"Available keys: {keys(asr_models)}."
        )
        variants = asr_models_property.get("anyOf", [])
        array_schema = next(
            (item for item in variants if item.get("type") == "array"), None
        )
        if array_schema is not None and asr_models:
            array_schema.setdefault("items", {})["enum"] = asr_models

    text_request = components.get("TextProcessRequest", {}).get("properties", {})
    for name in ("model", "models"):
        prop = text_request.get(name)
        if prop is None:
            continue
        prop["description"] += f" Available keys: {keys(llm_models)}."
        if not llm_models:
            continue
        variants = prop.get("anyOf", [])
        string_schema = next(
            (item for item in variants if item.get("type") == "string"), None
        )
        array_schema = next(
            (item for item in variants if item.get("type") == "array"), None
        )
        if string_schema is not None:
            string_schema["enum"] = llm_models
        if array_schema is not None:
            array_schema.setdefault("items", {})["enum"] = llm_models

    return schema


def create_app():
    """Create the application while keeping route assembly explicit and testable."""

    application = FastAPI(
        title="Persian ASR",
        version="2.0.0",
        description=DESCRIPTION,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        openapi_tags=TAGS,
        lifespan=lifespan,
    )
    application.add_middleware(GZipMiddleware, minimum_size=500)
    application.add_middleware(DynamicCORSMiddleware)
    application.add_middleware(RequestFailureAuditMiddleware)
    application.add_middleware(IngressAdmissionMiddleware)
    for router in (
        pages.router,
        models.router,
        analytics.router,
        proxy.router,
        ninerouter.router,
        ninerouter.proxy_router,
        security.router,
        openai_compat.router,
        tasks.router,
    ):
        application.include_router(router)

    @application.exception_handler(HTTPException)
    async def compatible_http_error(request: Request, exc: HTTPException):
        if request.url.path == "/v1/chat/tasks" or request.scope.get("chat_task"):
            codes = {401: "authentication_failed", 403: "access_denied", 404: "task_not_found", 429: "rate_limit_exceeded"}
            error = exc.detail if isinstance(exc.detail, dict) else {"code": codes.get(exc.status_code, "invalid_request"), "message": str(exc.detail)}
            return JSONResponse({"error": error}, status_code=exc.status_code, headers=exc.headers)
        if request.url.path.startswith(("/v1/chat/completions", "/v1/embeddings", "/v1/models")):
            error_type = "authentication_error" if exc.status_code == 401 else "permission_error" if exc.status_code == 403 else "rate_limit_error" if exc.status_code == 429 else "invalid_request_error"
            return JSONResponse({"error": {"message": str(exc.detail), "type": error_type, "param": None, "code": None}}, status_code=exc.status_code, headers=exc.headers)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    @application.exception_handler(RequestValidationError)
    async def compatible_validation_error(request: Request, exc: RequestValidationError):
        if request.url.path == "/v1/chat/tasks":
            first = exc.errors()[0]
            return JSONResponse({"error": {"code": "invalid_request", "message": first.get("msg", "Invalid request").split("Value error,")[-1].strip() if first.get("type") == "value_error" else "Invalid request body", "param": ".".join(str(x) for x in first.get("loc", ())[1:]) or None}}, status_code=400)
        if request.url.path.startswith(("/v1/chat/completions", "/v1/embeddings", "/v1/models")):
            first = exc.errors()[0]
            param = ".".join(str(value) for value in first.get("loc", ())[1:]) or None
            return JSONResponse({"error": {"message": first["msg"], "type": "invalid_request_error", "param": param, "code": None}}, status_code=400)
        return JSONResponse({"detail": exc.errors()}, status_code=422)

    def audience_schema(title, description, predicate):
        return get_openapi(
            title=title,
            version=application.version,
            description=description,
            routes=[
                route
                for route in application.routes
                if hasattr(route, "path") and predicate(route.path)
            ],
            tags=application.openapi_tags,
        )

    @application.get("/openapi/user.json", include_in_schema=False)
    def user_openapi():
        """Return the user-facing OpenAPI document for inference workflows."""

        return document_installed_models(
            audience_schema(
                "Persian ASR — User API",
                "User API for health, ordered single- or multi-model transcription, text processing, and asynchronous task management.",
                lambda path: path == "/health" or path.startswith("/v1/"),
            )
        )

    @application.get("/openapi/admin.json", include_in_schema=False)
    def admin_openapi():
        """Return the administrator OpenAPI document for operational workflows."""

        return audience_schema(
            "Persian ASR — Admin API",
            "Administrator API for models, parent-request analytics, ordered per-model execution logs, proxy configuration, and service health.",
            lambda path: path == "/health" or path.startswith("/api/"),
        )

    @application.get("/redoc", include_in_schema=False)
    @application.get("/redoc/user", include_in_schema=False)
    def user_redoc():
        """Render ReDoc for inference API consumers."""

        return get_redoc_html(
            openapi_url="/openapi/user.json",
            title="Persian ASR — User API Documentation",
        )

    @application.get("/redoc/admin", include_in_schema=False)
    def admin_redoc():
        """Render ReDoc for service administrators."""

        return get_redoc_html(
            openapi_url="/openapi/admin.json",
            title="Persian ASR — Admin API Documentation",
        )

    return application


app = create_app()
