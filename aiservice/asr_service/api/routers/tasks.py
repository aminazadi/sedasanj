"""Asynchronous text, transcription, status, result, and cancellation routes."""

import hashlib
import asyncio
import json
import os
import tempfile
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import PlainTextResponse

from asr_service.domain.catalog import CATALOG
from asr_service.infrastructure.storage import MODEL_DIR, connect, execute, now, row
from asr_service.infrastructure.failures import record_failure
from asr_service.infrastructure.ninerouter import NineRouterError, configured_models
from asr_service.services import object_storage
from asr_service.services.audio_compression import GzipAudioError, decompress_gzip
from asr_service.services.ingress import (
    HTTP_MAX_BODY_BYTES,
    UploadCapacityError,
    ensure_spool_capacity,
    upload_slot,
)
from asr_service.services.task_queue import (
    MAX_MODELS,
    QUEUE_LIMIT,
    TASK_DIR,
    enqueue,
    fingerprint,
    get_task,
    get_runs,
    IdempotencyConflict,
    log_task,
    public_task,
    queue_depth,
    _delete_input,
)

from ..dependencies import Principal, authorize, require_access
from ..openapi import documented_responses
from ..schemas.common import ChatTaskErrorResponse, ErrorResponse
from ..schemas.requests import DecisionRequest, TextProcessRequest
from ..schemas.uploads import (
    UploadCompleteRequest,
    UploadCreateRequest,
    UploadPartUrlResponse,
    UploadResponse,
    UploadTranscriptionRequest,
)
from ..schemas.responses import (
    ChatCompletionResultResponse,
    DecisionResultResponse,
    MeetingMinutesResultResponse,
    MultiModelResultResponse,
    TaskResponse,
    TextCorrectionResultResponse,
    TranscriptionResponse,
    VerboseTranscriptionResponse,
)

router = APIRouter(prefix="/v1")
MAX_UPLOAD_MB = int(os.getenv("ASR_MAX_UPLOAD_MB", "500"))
try:
    DECISION_SYNC_WAIT_SECONDS = max(0.0, min(10.0, float(os.getenv("ASR_DECISION_SYNC_WAIT_SECONDS", "0.25"))))
except ValueError:
    DECISION_SYNC_WAIT_SECONDS = 0.25
UPLOAD_TTL_HOURS = max(1, int(os.getenv("ASR_UPLOAD_TTL_HOURS", "24")))
try:
    DEFAULT_WHISPER_BEAM_SIZE = min(
        10, max(1, int(os.getenv("ASR_WHISPER_BEAM_SIZE", "2")))
    )
except ValueError:
    DEFAULT_WHISPER_BEAM_SIZE = 2


def accepted(task, response):
    """Apply the unchanged asynchronous-task response status and polling headers."""

    response.status_code = 202
    response.headers["Location"] = f"/v1/tasks/{task['task_id']}"
    response.headers["Retry-After"] = "2"
    return public_task(task, False)


def idempotency(value):
    """Normalize and validate an optional idempotency key."""

    if value is not None and (not value.strip() or len(value) > 200):
        raise HTTPException(400, "Idempotency-Key must be 1 to 200 characters")
    return value.strip() if value else None


@router.post(
    "/decisions",
    status_code=202,
    summary="Schedule a typed local decision",
    description="Queues a non-generative GLiNER or Laya decision. Poll the returned task URL for the normalized result.",
    responses=documented_responses(),
    tags=["Decision models"],
)
async def decision(
    body: DecisionRequest,
    response: Response,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(authorize),
):
    if body.model not in CATALOG or CATALOG[body.model].kind != "decision":
        raise HTTPException(422, "model must identify an installed decision model")
    if not (MODEL_DIR / body.model / ".complete").is_file():
        raise HTTPException(503, "The selected decision model is not installed")
    require_access(principal, "decision", [body.model])
    key = idempotency(idempotency_key)
    input_data = body.model_dump(exclude={"model"})
    try:
        task, _ = enqueue(
            "decision", models=[body.model], input_data=input_data,
            response_format="json", filename="decision",
            client_ip=request.client.host if request.client else None,
            idempotency_key=key,
            request_fingerprint=fingerprint("decision", [body.model], input_data, "json"),
            api_key_id=principal.key_id,
        )
    except IdempotencyConflict:
        raise HTTPException(409, "Idempotency-Key was already used with a different request")
    except OverflowError:
        raise HTTPException(503, "Task queue is full", headers={"Retry-After": "10"})
    deadline = asyncio.get_running_loop().time() + DECISION_SYNC_WAIT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        current = get_task(task["task_id"])
        if current and current["status"] == "succeeded":
            response.status_code = 200
            return public_task(current, True)
        if current and current["status"] in {"failed", "cancelled"}:
            break
        await asyncio.sleep(0.02)
    return accepted(task, response)


def owned_task(task, principal):
    if task and task["kind"] == "chat_async" and task.get("api_key_id") != principal.key_id:
        raise HTTPException(404, {"code": "task_not_found", "message": "Task not found"})
    if task and not principal.is_admin and task.get("api_key_id") != principal.key_id:
        raise HTTPException(404, "Task not found")
    return task


def authorize_task(request: Request, task_id: str, authorization: str | None = Header(default=None)):
    """Select the chat-task error envelope even for rejected credentials."""
    task = get_task(task_id)
    if task and task["kind"] == "chat_async":
        request.scope["chat_task"] = True
    return authorize(authorization)


def get_upload(upload_id):
    return row("SELECT * FROM uploads WHERE upload_id=?", (upload_id,))


def owned_upload(upload_id, principal):
    upload = get_upload(upload_id)
    if not upload or (not principal.is_admin and upload.get("api_key_id") != principal.key_id):
        raise HTTPException(404, "Upload not found")
    return upload


def upload_public(upload, include_part_endpoint=False):
    output = {
        key: upload.get(key)
        for key in ("upload_id", "status", "filename", "content_type", "audio_encoding", "uncompressed_audio_bytes", "expected_bytes", "actual_bytes", "sha256", "created_at", "expires_at", "task_id", "error")
    }
    output["part_size"] = object_storage.PART_SIZE
    if include_part_endpoint:
        output["part_url_endpoint"] = f"/v1/uploads/{upload['upload_id']}/parts/{{part_number}}"
        output["complete_url"] = f"/v1/uploads/{upload['upload_id']}/complete"
    return output


def ordered_models(single, multiple, kind):
    """Validate a backward-compatible single model or an ordered model list."""
    if (single is None) == (multiple is None):
        raise HTTPException(400, "Specify exactly one of model or models")
    values = (
        [single] if single is not None else [item.strip() for item in multiple or []]
    )
    if not values or len(values) > MAX_MODELS:
        raise HTTPException(400, f"models must contain 1 to {MAX_MODELS} items")
    if any(not item for item in values) or len(set(values)) != len(values):
        raise HTTPException(400, "models must contain unique, non-empty identifiers")
    try:
        remote = configured_models(kind)
    except NineRouterError as error:
        raise HTTPException(503, str(error))
    for model_id in values:
        local_model = CATALOG.get(model_id)
        local_available = (
            local_model is not None
            and local_model.kind == kind
            and (MODEL_DIR / model_id / ".complete").exists()
        )
        if not local_available and model_id not in remote:
            raise HTTPException(
                400,
                f"{kind.upper()} model '{model_id}' is not installed locally or "
                "available from the configured 9Router provider",
            )
        if (
            local_available
            and kind == "asr"
            and local_model.architecture in {"nemoCtc", "transducer"}
            and not (MODEL_DIR / "silero-vad" / ".complete").exists()
        ):
            raise HTTPException(503, "Install silero-vad before using Shenava")
    return values


TASK_ACCEPT_ERRORS = documented_responses(
    include_validation=True,
    **{
        "400": {
            "model": ErrorResponse,
            "description": "A semantic request option or idempotency key is invalid.",
        },
        "409": {
            "model": ErrorResponse,
            "description": "The Idempotency-Key was already used for different request content.",
        },
        "503": {
            "model": ErrorResponse,
            "description": "The selected model is unavailable or the task queue is full.",
        },
    },
)


@router.post(
    "/text/process",
    status_code=202,
    response_model=TaskResponse,
    summary="Schedule Persian text processing",
    description="Queues transcript correction or meeting-minutes generation with one model or an explicitly ordered failover list. Each model exhausts its retries before the next model runs, and processing stops after the first success. Reusing an Idempotency-Key with different content returns 409.",
    response_description="The accepted asynchronous task and its polling URL.",
    responses=TASK_ACCEPT_ERRORS,
    tags=["Text processing"],
)
async def text_process(
    body: TextProcessRequest,
    response: Response,
    request: Request,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="Optional 1–200 character key used to safely retry task creation.",
    ),
    principal: Principal = Depends(authorize),
):
    """Validate and enqueue an asynchronous Persian text-processing task."""

    models = ordered_models(body.model, body.models, "llm")
    require_access(principal, "text", models)
    if body.operation not in {"correction", "minutes"}:
        raise HTTPException(400, "operation must be correction or minutes")
    if body.style not in {"formal", "semi_formal", "action"}:
        raise HTTPException(400, "Unsupported style")
    key = idempotency(idempotency_key)
    input_data = body.model_dump(exclude={"model", "models"})
    request_fingerprint = fingerprint("text", models, input_data, "json")
    try:
        task, _ = enqueue(
            "text",
            models=models,
            input_data=input_data,
            response_format="json",
            filename=body.operation,
            client_ip=request.client.host if request.client else None,
            idempotency_key=key,
            request_fingerprint=request_fingerprint,
            api_key_id=principal.key_id,
        )
    except IdempotencyConflict:
        raise HTTPException(
            409, "Idempotency-Key was already used with a different request"
        )
    except OverflowError:
        raise HTTPException(503, "Task queue is full", headers={"Retry-After": "10"})
    return accepted(task, response)


@router.post(
    "/audio/transcriptions",
    status_code=202,
    response_model=TaskResponse,
    summary="Schedule an audio transcription",
    description="Uploads audio once and queues Persian speech recognition with either one model or an ordered failover list supplied through repeated `models` multipart fields. Each model exhausts its retries before the next model runs, and remaining models are skipped after the first success. Reusing an Idempotency-Key with different content returns 409.",
    response_description="The accepted asynchronous transcription task and its polling URL.",
    responses={
        **TASK_ACCEPT_ERRORS,
        413: {
            "model": ErrorResponse,
            "description": "The uploaded audio exceeds ASR_MAX_UPLOAD_MB.",
        },
    },
    tags=["Transcription"],
)
async def transcription(
    request: Request,
    response: Response,
    file: UploadFile = File(..., description="Audio file to transcribe."),
    audio_encoding: str = Form(
        "identity", description="Audio payload encoding: identity or gzip."
    ),
    model: str | None = Form(
        None, description="Legacy single installed ASR model identifier."
    ),
    models: list[str] | None = Form(
        None,
        description="Ordered installed ASR model identifiers; repeat this multipart field.",
    ),
    response_format: str = Form(
        "json",
        description="Result representation: json, verbose_json, text, srt, or vtt.",
    ),
    prompt: str | None = Form(
        None,
        description="Optional decoding prompt supported by compatible ASR engines.",
    ),
    beam_size: int = Form(
        DEFAULT_WHISPER_BEAM_SIZE,
        ge=1,
        le=10,
        description="Beam-search width. Defaults to ASR_WHISPER_BEAM_SIZE (2).",
    ),
    vad_filter: bool = Form(
        True, description="Whether voice activity detection should filter silence."
    ),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="Optional 1–200 character key used to safely retry task creation.",
    ),
    principal: Principal = Depends(authorize),
):
    """Validate, spool, and enqueue an asynchronous audio transcription."""

    selected_models = ordered_models(model, models, "asr")
    require_access(principal, "transcription", selected_models)
    if response_format not in {"json", "verbose_json", "text", "srt", "vtt"}:
        raise HTTPException(400, "Unsupported response_format")
    if audio_encoding not in {"identity", "gzip"}:
        raise HTTPException(400, "audio_encoding must be identity or gzip")
    key = idempotency(idempotency_key)
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    if queue_depth() >= QUEUE_LIMIT:
        raise HTTPException(503, "Task queue is full", headers={"Retry-After": "10"})
    guard = upload_slot()
    guard_entered = False
    try:
        await guard.__aenter__()
        guard_entered = True
        ensure_spool_capacity(TASK_DIR)
    except UploadCapacityError as exc:
        if guard_entered:
            await guard.__aexit__(type(exc), exc, exc.__traceback__)
        raise HTTPException(503, str(exc), headers={"Retry-After": "10"}) from exc
    temp = ""
    size = 0
    next_capacity_check = 16 * 1024 * 1024
    digest = hashlib.sha256()
    content_digest = None
    try:
        suffix = Path(file.filename or "audio").suffix
        if audio_encoding == "gzip" and suffix.lower() == ".gz":
            suffix = Path(Path(file.filename or "audio").stem).suffix or ".audio"
        with tempfile.NamedTemporaryFile(dir=TASK_DIR, suffix=suffix, delete=False) as output:
            temp = output.name
            if audio_encoding == "gzip":
                await file.seek(0)
                try:
                    result = decompress_gzip(
                        file.file, output, maximum_bytes=MAX_UPLOAD_MB * 1024 * 1024,
                        maximum_encoded_bytes=HTTP_MAX_BODY_BYTES,
                        on_progress=lambda decoded: ensure_spool_capacity(TASK_DIR, decoded),
                    )
                except GzipAudioError as exc:
                    message = str(exc)
                    raise HTTPException(413 if "large" in message else 400, message) from exc
                size = result["audio_bytes"]
                content_digest = result["sha256"]
            else:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_MB * 1024 * 1024:
                        raise HTTPException(413, "Audio file is too large")
                    if size >= next_capacity_check:
                        ensure_spool_capacity(TASK_DIR, size)
                        next_capacity_check += 16 * 1024 * 1024
                    digest.update(chunk)
                    output.write(chunk)
        input_data = {
            "beam_size": beam_size,
            "vad_filter": vad_filter,
            "prompt": prompt,
        }
        if audio_encoding == "gzip":
            input_data.update(
                audio_encoding="gzip",
                compressed_audio_bytes=result["compressed_bytes"],
                uncompressed_audio_bytes=size,
            )
        content_digest = content_digest or digest.hexdigest()
        task, created = enqueue(
            "asr",
            models=selected_models,
            input_path=temp,
            input_data=input_data,
            response_format=response_format,
            filename=file.filename,
            client_ip=request.client.host if request.client else None,
            idempotency_key=key,
            audio_bytes=size,
            request_fingerprint=fingerprint(
                "asr", selected_models, input_data, response_format, content_digest
            ),
            api_key_id=principal.key_id,
        )
        if not created:
            Path(temp).unlink(missing_ok=True)
        temp = ""
    except OverflowError:
        raise HTTPException(503, "Task queue is full", headers={"Retry-After": "10"})
    except IdempotencyConflict:
        raise HTTPException(
            409, "Idempotency-Key was already used with a different request"
        )
    except UploadCapacityError as exc:
        raise HTTPException(503, str(exc), headers={"Retry-After": "10"}) from exc
    finally:
        try:
            await file.close()
            if temp:
                Path(temp).unlink(missing_ok=True)
        finally:
            if guard_entered:
                await guard.__aexit__(None, None, None)
    return accepted(task, response)


@router.post(
    "/uploads",
    status_code=201,
    response_model=UploadResponse,
    summary="Create a direct multipart audio upload",
    description="Creates a private S3-compatible multipart upload. The client sends parts directly to object storage using short-lived presigned URLs; audio bytes never transit this API service.",
    responses=documented_responses(
        include_validation=True,
        **{
            "413": {"model": ErrorResponse, "description": "Declared file size exceeds ASR_MAX_UPLOAD_MB."},
            "503": {"model": ErrorResponse, "description": "Direct object storage is disabled or unavailable."},
        },
    ),
    tags=["Transcription"],
)
def create_upload(body: UploadCreateRequest, principal: Principal = Depends(authorize)):
    """Start a direct upload owned by the calling API key."""

    require_access(principal, "transcription")
    if not object_storage.enabled():
        raise HTTPException(503, "Direct object uploads are not configured")
    maximum = MAX_UPLOAD_MB * 1024 * 1024
    if body.audio_bytes > maximum:
        raise HTTPException(413, "Audio file is too large")
    if body.uncompressed_audio_bytes and body.uncompressed_audio_bytes > maximum:
        raise HTTPException(413, "Uncompressed audio file is too large")
    upload_id = uuid.uuid4().hex
    object_key = f"asr-uploads/{principal.key_id if principal.key_id is not None else 'admin'}/{upload_id}/{object_storage.safe_filename(body.filename)}"
    try:
        backend_id = object_storage.create_multipart(
            object_key,
            body.content_type,
            {"upload-id": upload_id, "sha256": body.sha256 or "", "audio-encoding": body.audio_encoding},
        )
    except Exception as exc:
        raise HTTPException(503, f"Object storage is unavailable: {type(exc).__name__}")
    stamp = now()
    expires = (datetime.now(timezone.utc) + timedelta(hours=UPLOAD_TTL_HOURS)).isoformat()
    try:
        execute(
            """INSERT INTO uploads(upload_id,api_key_id,status,created_at,updated_at,expires_at,filename,content_type,audio_encoding,uncompressed_audio_bytes,expected_bytes,sha256,object_key,backend_upload_id)
               VALUES(?,?, 'uploading',?,?,?,?,?,?,?,?,?,?,?,?)""",
            (upload_id, principal.key_id, stamp, stamp, expires, body.filename, body.content_type, body.audio_encoding, body.uncompressed_audio_bytes, body.audio_bytes, body.sha256, object_key, backend_id),
        )
    except Exception:
        try:
            object_storage.abort_multipart(object_key, backend_id)
        finally:
            raise
    return upload_public(get_upload(upload_id), include_part_endpoint=True)


@router.post(
    "/uploads/{upload_id}/parts/{part_number}",
    response_model=UploadPartUrlResponse,
    summary="Get a presigned URL for one upload part",
    description="Returns a short-lived PUT URL for exactly one part of an active multipart upload.",
    responses=documented_responses(
        include_validation=True,
        **{
            "400": {"model": ErrorResponse, "description": "Part number is outside the declared upload range."},
            "404": {"model": ErrorResponse, "description": "Upload does not exist or belongs to another API key."},
            "409": {"model": ErrorResponse, "description": "Upload is no longer accepting parts."},
            "410": {"model": ErrorResponse, "description": "Upload session has expired."},
            "503": {"model": ErrorResponse, "description": "Object storage is unavailable."},
        },
    ),
    tags=["Transcription"],
)
def upload_part_url(upload_id: str, part_number: int, principal: Principal = Depends(authorize)):
    require_access(principal, "transcription")
    upload = owned_upload(upload_id, principal)
    if upload["status"] != "uploading":
        raise HTTPException(409, f"Upload is {upload['status']}")
    if datetime.fromisoformat(upload["expires_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(410, "Upload session has expired")
    total_parts = (upload["expected_bytes"] + object_storage.PART_SIZE - 1) // object_storage.PART_SIZE
    if part_number < 1 or part_number > total_parts:
        raise HTTPException(400, f"part_number must be between 1 and {total_parts}")
    try:
        return {"part_number": part_number, "url": object_storage.part_url(upload["object_key"], upload["backend_upload_id"], part_number), "expires_in": object_storage.URL_TTL_SECONDS}
    except Exception as exc:
        raise HTTPException(503, f"Object storage is unavailable: {type(exc).__name__}")


@router.post(
    "/uploads/{upload_id}/complete",
    response_model=UploadResponse,
    summary="Complete a direct multipart audio upload",
    description="Assembles the uploaded parts and verifies the final object size before it can be scheduled for transcription.",
    responses=documented_responses(
        include_validation=True,
        **{
            "400": {"model": ErrorResponse, "description": "Part list or completed object size is invalid."},
            "404": {"model": ErrorResponse, "description": "Upload does not exist or belongs to another API key."},
            "409": {"model": ErrorResponse, "description": "Upload was already completed or is unavailable."},
            "502": {"model": ErrorResponse, "description": "Object storage could not complete the multipart upload."},
        },
    ),
    tags=["Transcription"],
)
def complete_upload(upload_id: str, body: UploadCompleteRequest, principal: Principal = Depends(authorize)):
    require_access(principal, "transcription")
    upload = owned_upload(upload_id, principal)
    if upload["status"] != "uploading":
        raise HTTPException(409, f"Upload is {upload['status']}")
    expected_parts = (upload["expected_bytes"] + object_storage.PART_SIZE - 1) // object_storage.PART_SIZE
    numbers = [part.part_number for part in body.parts]
    if numbers != list(range(1, expected_parts + 1)):
        raise HTTPException(400, "parts must contain every part number exactly once in ascending order")
    parts = [part.model_dump() for part in body.parts]
    try:
        object_storage.complete_multipart(upload["object_key"], upload["backend_upload_id"], parts)
        metadata = object_storage.head(upload["object_key"])
    except Exception as exc:
        raise HTTPException(502, f"Could not complete object upload: {type(exc).__name__}")
    actual = metadata.get("ContentLength", -1)
    if actual != upload["expected_bytes"]:
        try:
            object_storage.delete(upload["object_key"])
        finally:
            execute("UPDATE uploads SET status='failed',updated_at=?,actual_bytes=?,error=? WHERE upload_id=?", (now(), actual, "Object size did not match declared size", upload_id))
        raise HTTPException(400, "Uploaded object size does not match declared size")
    if upload.get("audio_encoding") == "gzip":
        try:
            source = object_storage.open_object(upload["object_key"])
            try:
                result = decompress_gzip(
                    source, None, maximum_bytes=MAX_UPLOAD_MB * 1024 * 1024,
                    expected_bytes=upload["uncompressed_audio_bytes"],
                )
            finally:
                source.close()
            if result["compressed_bytes"] != actual:
                raise GzipAudioError("Compressed audio size does not match uploaded object")
        except GzipAudioError as exc:
            try:
                object_storage.delete(upload["object_key"])
            finally:
                execute("UPDATE uploads SET status='failed',updated_at=?,actual_bytes=?,error=? WHERE upload_id=?", (now(), actual, str(exc), upload_id))
            raise HTTPException(413 if "large" in str(exc) else 400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"Could not validate gzip upload: {type(exc).__name__}")
    execute("UPDATE uploads SET status='completed',updated_at=?,actual_bytes=?,backend_upload_id='' WHERE upload_id=?", (now(), actual, upload_id))
    return upload_public(get_upload(upload_id))


@router.post(
    "/uploads/{upload_id}/transcriptions",
    status_code=202,
    response_model=TaskResponse,
    summary="Schedule transcription from a completed direct upload",
    description="Queues a completed private object for ASR. The worker downloads it only when inference capacity is available.",
    responses={
        **TASK_ACCEPT_ERRORS,
        "404": {"model": ErrorResponse, "description": "Upload does not exist or belongs to another API key."},
    },
    tags=["Transcription"],
)
def transcribe_upload(
    upload_id: str,
    body: UploadTranscriptionRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(authorize),
):
    require_access(principal, "transcription")
    upload = owned_upload(upload_id, principal)
    if upload["status"] != "completed":
        raise HTTPException(409, f"Upload is {upload['status']}")
    selected_models = ordered_models(body.model, body.models, "asr")
    require_access(principal, "transcription", selected_models)
    if body.response_format not in {"json", "verbose_json", "text", "srt", "vtt"}:
        raise HTTPException(400, "Unsupported response_format")
    key = idempotency(idempotency_key)
    input_data = {"beam_size": body.beam_size, "vad_filter": body.vad_filter, "prompt": body.prompt, "sha256": upload.get("sha256")}
    if upload.get("audio_encoding") == "gzip":
        input_data.update(
            audio_encoding="gzip",
            uncompressed_audio_bytes=upload["uncompressed_audio_bytes"],
            compressed_audio_bytes=upload["actual_bytes"],
        )
    try:
        task, created = enqueue(
            "asr", models=selected_models, input_path=f"s3://{upload['object_key']}", input_data=input_data,
            response_format=body.response_format, filename=upload["filename"], client_ip=None,
            idempotency_key=key, audio_bytes=upload.get("uncompressed_audio_bytes") or upload["actual_bytes"],
            request_fingerprint=fingerprint("asr", selected_models, input_data, body.response_format, upload.get("sha256") or upload_id),
            api_key_id=principal.key_id,
        )
    except OverflowError:
        raise HTTPException(503, "Task queue is full", headers={"Retry-After": "10"})
    except IdempotencyConflict:
        raise HTTPException(409, "Idempotency-Key was already used with a different request")
    if created:
        execute("UPDATE uploads SET status='scheduled',updated_at=?,task_id=? WHERE upload_id=?", (now(), task["task_id"], upload_id))
    return accepted(task, response)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    summary="Get task status",
    description="Returns lifecycle metadata, ordered failover models, the current model, progress, and result availability. Completed multi-model tasks expose failed attempts, the first successful result, and models skipped after success.",
    responses=documented_responses(
        **{
            "404": {
                "model": ErrorResponse | ChatTaskErrorResponse,
                "description": "No task exists with the supplied identifier.",
            }
        }
    ),
    tags=["Tasks"],
)
def task_status(task_id: str, request: Request, principal: Principal = Depends(authorize_task)):
    """Return public state and resource links for an asynchronous task."""

    task = get_task(task_id)
    if task and task["kind"] == "chat_async":
        request.scope["chat_task"] = True
        require_access(principal, "chat", [task["model_id"]])
    else:
        require_access(principal, "inference")
    task = owned_task(task, principal)
    if not task:
        raise HTTPException(404, "Task not found")
    result = public_task(task, False)
    if task["status"] in {"queued", "retrying"}:
        result["queue_position"] = row(
            "SELECT count(*) n FROM tasks WHERE status IN ('queued','retrying') AND created_at<=?",
            (task["created_at"],),
        )["n"]
    return result


def ts(seconds, decimal=","):
    """Format seconds as an SRT or WebVTT timestamp."""

    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{decimal}{milliseconds:03}"


def subtitles(segments, vtt=False):
    """Serialize timestamped segments to SRT or WebVTT without changing content."""

    return (
        ("WEBVTT\n\n" if vtt else "")
        + "\n\n".join(
            ("" if vtt else f"{index}\n")
            + f"{ts(segment['start'], '.' if vtt else ',')} --> {ts(segment['end'], '.' if vtt else ',')}\n{segment['text']}"
            for index, segment in enumerate(segments, 1)
        )
        + "\n"
    )


RESULT_RESPONSES = documented_responses(
    **{
        "200": {
            "description": "Completed task result. The representation follows the format selected when the task was created.",
            "model": TextCorrectionResultResponse
            | ChatCompletionResultResponse
            | DecisionResultResponse
            | MeetingMinutesResultResponse
            | TranscriptionResponse
            | VerboseTranscriptionResponse
            | MultiModelResultResponse,
            "content": {
                "text/plain": {
                    "schema": {
                        "type": "string",
                        "description": "Plain transcript text.",
                    }
                },
                "application/x-subrip": {
                    "schema": {"type": "string", "description": "SRT subtitles."}
                },
                "text/vtt": {
                    "schema": {"type": "string", "description": "WebVTT subtitles."}
                },
            },
        },
        "404": {
            "model": ErrorResponse | ChatTaskErrorResponse,
            "description": "No task exists with the supplied identifier.",
        },
        "409": {
            "model": ErrorResponse | ChatTaskErrorResponse,
            "description": "The task has not succeeded, so its result is unavailable.",
        },
    }
)


@router.get(
    "/tasks/{task_id}/result",
    summary="Get a completed task result",
    description="Returns a completed task result. Single-model media types remain backward compatible; multi-model tasks return an ordered JSON envelope containing failed attempts, the first success, and skipped models.",
    responses=RESULT_RESPONSES,
    tags=["Tasks"],
)
def task_result(task_id: str, request: Request, principal: Principal = Depends(authorize_task)):
    """Return a completed task result in its originally requested format."""

    task = get_task(task_id)
    if task and task["kind"] == "chat_async":
        request.scope["chat_task"] = True
        require_access(principal, "chat", [task["model_id"]])
    else:
        require_access(principal, "inference")
    task = owned_task(task, principal)
    if not task:
        raise HTTPException(404, "Task not found")
    runs = get_runs(task_id)
    if task["status"] not in {"succeeded", "partially_succeeded"} and not (
        task["status"] == "failed" and len(runs) > 1 and task.get("result_json")
    ):
        if task["kind"] == "chat_async":
            raise HTTPException(409, {"code": "result_not_ready" if task["status"] not in {"failed", "cancelled"} else ("task_cancelled" if task["status"] == "cancelled" else "task_timeout" if any(x.get("error") == "task_timeout" for x in runs) else "model_failure"), "message": f"Task is {task['status']}"}, headers={"Retry-After": "2"} if task["status"] in {"queued", "retrying", "running"} else None)
        raise HTTPException(
            409,
            f"Task is {task['status']}",
            headers=(
                {"Retry-After": "2"}
                if task["status"] not in {"failed", "cancelled"}
                else None
            ),
        )
    result = json.loads(task["result_json"])
    if len(runs) > 1:
        return result
    if task["kind"] == "chat_async":
        return result
    if task["kind"] == "decision":
        return result
    if task["kind"] == "text":
        return result
    if task["response_format"] == "text":
        return PlainTextResponse(result["text"])
    if task["response_format"] == "srt":
        return PlainTextResponse(
            subtitles(result["segments"]), media_type="application/x-subrip"
        )
    if task["response_format"] == "vtt":
        return PlainTextResponse(
            subtitles(result["segments"], True), media_type="text/vtt"
        )
    if task["response_format"] == "json":
        return {"text": result["text"]}
    return result


@router.delete(
    "/tasks/{task_id}",
    status_code=202,
    response_model=TaskResponse,
    summary="Request task cancellation",
    description="Cancels queued tasks immediately and marks running tasks for cancellation at the next safe checkpoint. Completed tasks remain unchanged.",
    responses=documented_responses(
        **{
            "404": {
                "model": ErrorResponse | ChatTaskErrorResponse,
                "description": "No task exists with the supplied identifier.",
            }
        }
    ),
    tags=["Tasks"],
)
def cancel_task(task_id: str, request: Request, principal: Principal = Depends(authorize_task)):
    """Cancel or request cancellation of an asynchronous task."""

    task = get_task(task_id)
    if task and task["kind"] == "chat_async":
        request.scope["chat_task"] = True
        require_access(principal, "chat", [task["model_id"]])
    else:
        require_access(principal, "inference")
    task = owned_task(task, principal)
    if not task:
        raise HTTPException(404, "Task not found")
    if task["status"] in {"queued", "retrying"}:
        stamp = now()
        with closing(connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE tasks SET status='cancelled',cancel_requested=1,finished_at=?,updated_at=? WHERE task_id=?",
                (stamp, stamp, task_id),
            )
            db.execute(
                "UPDATE usage SET status='failed',finished_at=?,error='Cancelled' WHERE id=?",
                (stamp, task.get("usage_id")),
            )
            db.execute(
                "UPDATE task_runs SET status='skipped',finished_at=?,updated_at=?,error='Skipped after cancellation' WHERE task_id=? AND status IN ('pending','retrying')",
                (stamp, stamp, task_id),
            )
        record_failure(
            phase="processing",
            reason="task_cancelled",
            detail="Task was cancelled before processing completed",
            task_id=task_id,
            usage_id=task.get("usage_id"),
            client_ip=task.get("client_ip"),
            dedupe_key=f"task:{task_id}:cancelled",
        )
        log_task(task_id, "Task was cancelled before execution", "warning", "cancelled")
        if task["input_path"]:
            _delete_input(task["input_path"])
    elif task["status"] == "running":
        execute(
            "UPDATE tasks SET cancel_requested=1,updated_at=? WHERE task_id=?",
            (now(), task_id),
        )
    return public_task(get_task(task_id), False)
