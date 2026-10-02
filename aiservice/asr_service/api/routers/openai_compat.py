"""OpenAI Chat Completions compatibility for installed local LLMs."""

import asyncio
import json
import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from asr_service.domain.catalog import CATALOG
from asr_service.infrastructure.ninerouter import (
    NineRouterError,
    cached_models,
    configured_model,
)
from asr_service.infrastructure.storage import MODEL_DIR
from asr_service.services.task_queue import (
    IdempotencyConflict,
    enqueue,
    fingerprint,
    get_by_key,
    get_task,
    public_task,
)

from ..dependencies import Principal, authorize, require_access
from ..schemas.common import ChatTaskErrorResponse
from ..schemas.responses import TaskResponse

router = APIRouter(prefix="/v1", tags=["OpenAI compatibility"])
SYNC_CHAT_WAIT_SECONDS = max(
    1, int(os.getenv("ASR_SYNC_CHAT_WAIT_SECONDS", "120"))
)


class ChatMessage(BaseModel):
    role: str
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[ChatMessage] = Field(min_length=1, max_length=64)
    temperature: float | None = Field(default=1, ge=0, le=2)
    top_p: float | None = Field(default=1, ge=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=4096)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=4096)
    stream: bool = False
    stop: str | list[str] | None = None
    seed: int | None = None
    presence_penalty: float | None = Field(default=0, ge=-2, le=2)
    frequency_penalty: float | None = Field(default=0, ge=-2, le=2)
    user: str | None = None
    tools: list[dict[str, Any]] | None = Field(default=None, max_length=32)
    tool_choice: str | dict[str, Any] | None = None

    @model_validator(mode="after")
    def bounded_text_only_input(self):
        total = 0
        for message in self.messages:
            if message.role not in {"system", "user", "assistant", "tool"}:
                raise ValueError("Unsupported chat message role")
            if not isinstance(message.content, (str, type(None))):
                raise TypeError("This local model supports text message content only")
            total += len(message.content or "")
        if total > 24000:
            raise ValueError("Total message content must not exceed 24000 characters")
        return self


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=200)
    input: str | list[str]
    encoding_format: str = Field(default="float", pattern="^float$")

    @model_validator(mode="after")
    def validate_input(self):
        values = [self.input] if isinstance(self.input, str) else self.input
        if not values or len(values) > 128:
            raise ValueError("input must contain one to 128 texts")
        if any(not value.strip() or len(value) > 12000 for value in values):
            raise ValueError("each input must contain one to 12000 non-whitespace characters")
        if sum(len(value) for value in values) > 100000:
            raise ValueError("combined input is too large")
        return self

class AsyncChatRequest(BaseModel):
    """Text-only, freely instructed chat inference without a long HTTP connection."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "model": "dorna-8b-q4_k_m",
        "messages": [{"role": "system", "content": "تماس را تحلیل کن؛ فقط JSON با summary برگردان."},
                     {"role": "user", "content": "متن تماس فارسی..."}],
        "temperature": 0.2, "max_tokens": 1024,
    }]})
    model: str
    messages: list[ChatMessage] = Field(min_length=1, max_length=64)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=4096)
    tools: list[dict[str, Any]] | None = Field(default=None, max_length=32)
    tool_choice: str | dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_messages(self):
        if any(m.role not in {"system", "user", "assistant", "tool"}
               or not isinstance(m.content, (str, type(None)))
               for m in self.messages):
            raise ValueError("Only OpenAI-compatible text and tool messages are supported")
        if sum(len(m.content or "") for m in self.messages) > 24000:
            raise ValueError("Total message content must not exceed 24000 characters")
        return self


def chat_task_error(status, code, message, headers=None):
    raise HTTPException(status, {"code": code, "message": message}, headers=headers)


@router.post(
    "/chat/tasks", status_code=202,
    response_model=TaskResponse,
    summary="Schedule durable asynchronous chat completion",
    description="Persist a custom system/user prompt immediately. Poll status_url and retrieve the complete chat.completion from result_url after success. Result TTL and idempotency lifetime default to 168 hours after completion; interrupted attempts are retried within the configured attempt limit.",
    responses={code: {"description": description, "model": ChatTaskErrorResponse}
               for code, description in {400: "Invalid request or idempotency key.",
                                         401: "Authentication failed.", 403: "Access denied.",
                                         404: "Text model unavailable.", 409: "Idempotency key conflict.",
                                         503: "Task queue full."}.items()},
)
def create_chat_task(
    body: AsyncChatRequest, request: Request, response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(authorize),
):
    require_access(principal, "chat", [body.model])
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key or len(idempotency_key) > 200:
            chat_task_error(400, "invalid_idempotency_key", "Idempotency-Key must be 1 to 200 characters")
    if not installed_llm(body.model) and not get_by_key(idempotency_key, principal.key_id):
        chat_task_error(404, "model_unavailable", "The requested text model is not installed")
    options = {"temperature": body.temperature, "max_tokens": body.max_tokens, "stream": False}
    if body.tools:
        options["tools"] = body.tools
        options["tool_choice"] = body.tool_choice or "auto"
    data = {"messages": [m.model_dump(exclude_none=True) for m in body.messages],
            "options": options}
    try:
        task, _ = enqueue(
            "chat_async", models=[body.model], input_data=data, response_format="json",
            filename="chat.tasks", idempotency_key=idempotency_key,
            request_fingerprint=fingerprint("chat_async", [body.model], data, "json"),
            api_key_id=principal.key_id,
        )
    except IdempotencyConflict:
        chat_task_error(409, "idempotency_conflict", "Idempotency-Key was used for different request content")
    except OverflowError:
        chat_task_error(503, "queue_full", "Task queue is full", {"Retry-After": "10"})
    response.headers["Location"] = f"/v1/tasks/{task['task_id']}"
    response.headers["Retry-After"] = "2"
    return public_task(task, False)


def installed_llm(model_id):
    try:
        if configured_model("llm") == model_id:
            return True
    except NineRouterError:
        return False
    return (
        model_id in CATALOG
        and CATALOG[model_id].kind == "llm"
        and (MODEL_DIR / model_id / ".complete").exists()
    )


def model_object(model_id):
    if configured_model("llm") == model_id:
        return {
            "id": model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "9router",
            "kind": "llm",
            "source": "9router",
            "available": True,
            "status": "ready",
        }
    return {
        "id": model_id,
        "object": "model",
        "created": int((MODEL_DIR / model_id / ".complete").stat().st_mtime),
        "owned_by": "persian-asr-service",
        "kind": CATALOG[model_id].kind,
        "source": "local",
        "available": True,
        "status": "ready",
    }


def remote_model_object(item):
    return {
        "id": item["id"],
        "object": "model",
        "created": int(time.time()),
        "owned_by": item.get("owned_by", "9router"),
        "kind": item["kind"],
        "source": "9router",
        "available": True,
        "status": "ready",
    }


@router.get(
    "/models",
    summary="List models",
    description="Lists active local models and the persisted 9Router model snapshot. Use kind to filter categories; model synchronization is administrator-controlled.",
)
def list_models(kind: str = Query(default="llm", pattern="^(llm|asr|decision|tts|embedding|image|video|web|vision|all)$"), principal: Principal = Depends(authorize)):
    accessible_kinds = set()
    for model_kind, scope in (("llm", "chat"), ("asr", "transcription"), ("decision", "decision"), ("tts", "inference"), ("embedding", "embedding"), ("image", "inference"), ("video", "inference"), ("web", "inference"), ("vision", "inference")):
        try:
            require_access(principal, scope)
        except HTTPException as error:
            if error.status_code != 403:
                raise
        else:
            accessible_kinds.add(model_kind)
    if kind != "all":
        accessible_kinds.intersection_update((kind,))
    if not accessible_kinds:
        raise HTTPException(403, "API key does not allow model listing")
    remote = [remote_model_object(item) for item in cached_models() if item.get("kind") in accessible_kinds and (principal.models is None or item["id"] in principal.models)]
    return {
        "object": "list",
        "data": remote + [
            model_object(model_id)
            for model_id, spec in CATALOG.items()
            if spec.kind in accessible_kinds
            and (MODEL_DIR / model_id / ".complete").is_file()
            and (principal.models is None or model_id in principal.models)
        ],
    }


@router.post(
    "/embeddings",
    summary="Create embeddings",
    description="Creates normalized embeddings with an installed local transformer model.",
)
async def create_embeddings(body: EmbeddingRequest, principal: Principal = Depends(authorize)):
    require_access(principal, "embedding", [body.model])
    values = [body.input] if isinstance(body.input, str) else body.input
    from asr_service.services.embedding_processing import embed

    vectors, prompt_tokens = await run_in_threadpool(embed, body.model, values)
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": vector, "index": index}
            for index, vector in enumerate(vectors)
        ],
        "model": body.model,
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
    }


@router.get(
    "/models/{model_id}",
    summary="Retrieve a model",
    description="Returns one installed OpenAI-compatible text model.",
)
def retrieve_model(model_id: str, principal: Principal = Depends(authorize)):
    require_access(principal, "chat", [model_id])
    if not installed_llm(model_id):
        raise HTTPException(
            404, f"The model '{model_id}' does not exist or is not installed"
        )
    return model_object(model_id)


@router.post(
    "/chat/completions",
    summary="Create a chat completion",
    description="OpenAI-compatible synchronous or SSE-streaming chat completion using an installed local GGUF model.",
)
async def create_completion(
    body: ChatCompletionRequest,
    request: Request,
    principal: Principal = Depends(authorize),
):
    require_access(principal, "chat", [body.model])
    if not installed_llm(body.model):
        raise HTTPException(
            404, f"The model '{body.model}' does not exist or is not installed"
        )
    if body.max_tokens and body.max_completion_tokens:
        raise HTTPException(400, "Specify only one of max_tokens or max_completion_tokens")
    messages = [message.model_dump(exclude_none=True) for message in body.messages]
    options = {
        "temperature": body.temperature,
        "top_p": body.top_p,
        "max_tokens": body.max_completion_tokens or body.max_tokens or 1024,
        "stream": False,
        "stop": body.stop,
        "seed": body.seed,
        "presence_penalty": body.presence_penalty,
        "frequency_penalty": body.frequency_penalty,
    }
    if body.tools:
        options["tools"] = body.tools
        options["tool_choice"] = body.tool_choice or "auto"
    options = {key: value for key, value in options.items() if value is not None}
    try:
        task, _ = await run_in_threadpool(
            enqueue,
            "chat",
            models=[body.model],
            input_data={"messages": messages, "options": options},
            response_format="json",
            filename="chat.completions",
            client_ip=request.client.host if request.client else None,
            request_fingerprint=fingerprint(
                "chat",
                [body.model],
                {"messages": messages, "options": options},
                "json",
            ),
            api_key_id=principal.key_id,
        )
    except OverflowError:
        raise HTTPException(503, "Task queue is full", headers={"Retry-After": "10"})
    task_id = task["task_id"]
    deadline = time.monotonic() + SYNC_CHAT_WAIT_SECONDS
    while task["status"] not in {"succeeded", "partially_succeeded", "failed", "cancelled"}:
        if time.monotonic() >= deadline:
            raise HTTPException(
                504,
                "Chat completion is still processing; use the asynchronous task API for long-running work",
                headers={"Retry-After": "2", "Location": f"/v1/tasks/{task_id}"},
            )
        if await request.is_disconnected():
            raise HTTPException(499, "Client disconnected while waiting for completion")
        await asyncio.sleep(.2)
        task = await run_in_threadpool(get_task, task_id)
    if task["status"] != "succeeded":
        raise HTTPException(500, task.get("error") or "Local model inference failed")
    result = json.loads(task["result_json"])
    result["id"] = result.get("id") or "chatcmpl-" + uuid.uuid4().hex
    result["object"] = "chat.completion"
    result["created"] = result.get("created") or int(time.time())
    result["model"] = body.model

    if not body.stream:
        return result

    def events():
        content = ((result.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        chunk = {"id": result["id"], "object": "chat.completion.chunk", "created": result["created"], "model": body.model, "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": "stop"}]}
        yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
