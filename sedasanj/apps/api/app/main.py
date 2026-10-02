from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from copy import deepcopy

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import get_settings
from app.db import assert_database_runtime_ready, assert_rls_enforced, dispose_engine
from app.errors import install_error_handlers
from app.logging import configure_logging, log_context
from app.metrics import http_request_seconds, http_requests_total
from app.routers import (
    account,
    admin,
    assistant,
    auth,
    billing,
    calls,
    commerce,
    health,
    ingest,
    kpi,
    tasks,
    webhooks,
)
from app.services.queue import get_queue
from app.services.ratelimit import close_redis
from app.services.storage import get_storage

API_TITLE = "sedasanj (voicesanj)"


def _referenced_component_schemas(value: object) -> set[str]:
    referenced: set[str] = set()
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            referenced.add(ref.rsplit("/", 1)[-1])
        for child in value.values():
            referenced.update(_referenced_component_schemas(child))
    elif isinstance(value, list):
        for child in value:
            referenced.update(_referenced_component_schemas(child))
    return referenced


def _prune_unreferenced_schemas(schema: dict[str, object]) -> None:
    components = schema.get("components")
    paths = schema.get("paths")
    if not isinstance(components, dict) or not isinstance(paths, dict):
        return
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        return

    required = _referenced_component_schemas(paths)
    pending = list(required)
    while pending:
        name = pending.pop()
        dependencies = _referenced_component_schemas(schemas.get(name))
        for dependency in dependencies - required:
            required.add(dependency)
            pending.append(dependency)
    components["schemas"] = {
        name: definition for name, definition in schemas.items() if name in required
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.service_name, settings.log_level)
    await assert_rls_enforced()
    await assert_database_runtime_ready()
    await get_storage().ensure_bucket()
    yield
    await get_queue().close()
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title=API_TITLE,
        version="1.0.0",
        description="Post-call Persian voice analytics (ASR + LLM), multi-tenant.",
        lifespan=lifespan,
    )
    settings = get_settings()
    origins = settings.cors_origin_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=None if origins else r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "authorization",
            "content-type",
            "idempotency-key",
            "x-api-key",
            "x-cbi-archive-password",
        ],
    )

    @app.middleware("http")
    async def observability(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        log_context(request_id=request_id, tenant_id=None, call_id=None)
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        http_requests_total.labels(
            method=request.method, path=path, status=str(response.status_code)
        ).inc()
        http_request_seconds.labels(method=request.method, path=path).observe(elapsed)
        response.headers["X-Request-ID"] = request_id
        return response

    install_error_handlers(app)
    for module in (
        health,
        auth,
        ingest,
        calls,
        tasks,
        billing,
        commerce,
        webhooks,
        account,
        assistant,
        kpi,
        admin,
    ):
        app.include_router(module.router)

    @app.get("/v1/openapi/customer.json", include_in_schema=False)
    async def customer_openapi() -> JSONResponse:
        schema = deepcopy(app.openapi())
        schema["info"] = {
            "title": API_TITLE,
            "version": "1.0.0",
            "description": (
                "Customer and Asterisk integration API. Archive uploads use the format "
                "configured on each API key."
            ),
        }
        schema["paths"] = {
            path: operations
            for path, operations in schema.get("paths", {}).items()
            if path.startswith("/v1/") and not path.startswith("/v1/admin")
        }
        _prune_unreferenced_schemas(schema)
        components = schema.setdefault("components", {})
        components["securitySchemes"] = {
            "CustomerJWT": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
            "AgentBearer": {"type": "http", "scheme": "bearer"},
            "AgentHeader": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
        }
        for path, operations in schema.get("paths", {}).items():
            if path in {"/v1/auth/login", "/v1/auth/refresh"}:
                security: list[dict[str, list[str]]] = []
            elif path.startswith("/v1/ingest/") or path.startswith("/v1/crm/"):
                security = [{"AgentBearer": []}, {"AgentHeader": []}]
            else:
                security = [{"CustomerJWT": []}]
            for operation in operations.values():
                if isinstance(operation, dict):
                    operation["security"] = security
                    operation["parameters"] = [
                        parameter
                        for parameter in operation.get("parameters", [])
                        if str(parameter.get("name", "")).lower()
                        not in {"authorization", "x-api-key"}
                    ]
        ingest_operation = schema["paths"]["/v1/ingest/calls"]["post"]
        ingest_operation["description"] = f"""
Upload one call using the archive format configured on the authenticated API key.
The request must use HTTPS and `multipart/form-data`. Authentication accepts either
`Authorization: Bearer <api-key>` or `X-API-Key: <api-key>`.

Required form fields: `file`, `asterisk_uniqueid`, `caller_number`, `dialed_number`,
`started_at`, and `ended_at`. Optional fields: `direction`, `agent_extension`,
`campaign_id`, `source`, and `external_reference`.
Send `Idempotency-Key` to make retries safe; the Asterisk unique ID is also deduplicated.

```bash
gzip -c call.wav > call.wav.gz
curl -X POST "$CBI_URL/v1/ingest/calls" \\
  -H "Authorization: Bearer $CBI_API_KEY" \\
  -H "Idempotency-Key: 1750000000.42" \\
  -F "file=@call.wav.gz;type=application/gzip" \\
  -F "asterisk_uniqueid=1750000000.42" \\
  -F "caller_number=09120000000" -F "dialed_number=1000" \\
  -F "started_at=2026-09-21T08:00:00Z" -F "ended_at=2026-09-21T08:02:00Z"
```

For password-protected ZIP, create an AES-256 archive containing exactly one root-level
WAV and add `X-CBI-Archive-Password`. Never put the password in a URL or query string.

```bash
7z a -tzip -mem=AES256 -p"$CBI_ARCHIVE_PASSWORD" call.zip call.wav
curl -X POST "$CBI_URL/v1/ingest/calls" \\
  -H "X-API-Key: $CBI_API_KEY" \\
  -H "X-CBI-Archive-Password: $CBI_ARCHIVE_PASSWORD" \\
  -H "Idempotency-Key: 1750000000.42" \\
  -F "file=@call.zip;type=application/zip" \\
  -F "asterisk_uniqueid=1750000000.42" \\
  -F "caller_number=09120000000" -F "dialed_number=1000" \\
  -F "started_at=2026-09-21T08:00:00Z" -F "ended_at=2026-09-21T08:02:00Z"
```

Compressed uploads are limited to {settings.max_upload_bytes // (1024 * 1024)} MiB;
the extracted WAV is limited to {settings.max_extracted_audio_bytes // (1024 * 1024)} MiB;
the maximum compression ratio is {settings.max_archive_compression_ratio}:1. ZIP rejects
multiple entries, directories, links, nested paths, non-WAV files, unsafe paths, non-AES
encryption, and AES strengths below 256 bits. GZIP must extract to one valid WAV stream.
The extracted file must pass the PCM, sample-rate, channel, and duration checks.
""".strip()
        ingest_responses = ingest_operation.setdefault("responses", {})
        ingest_responses.update(
            {
                "400": {"description": "Invalid metadata or malformed request."},
                "401": {"description": "Missing, invalid, or revoked API key."},
                "402": {"description": "Insufficient processing credit."},
                "413": {"description": "Compressed or extracted file exceeds a limit."},
                "415": {"description": "Unsupported archive or invalid WAV media."},
                "422": {
                    "description": (
                        "Archive format mismatch, unsafe archive, or missing/invalid ZIP password."
                    )
                },
                "429": {"description": "Rate limit exceeded; retry with backoff."},
            }
        )
        return JSONResponse(schema)

    @app.get("/v1/docs/customer", include_in_schema=False, response_class=HTMLResponse)
    async def customer_docs() -> HTMLResponse:
        return get_redoc_html(
            openapi_url="/v1/openapi/customer.json",
            title=API_TITLE,
        )

    return app


app = create_app()
