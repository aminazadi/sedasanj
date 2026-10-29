from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
import socketio
from sqlalchemy import delete, select, text
from starlette.requests import Request

from app.config import get_settings
from app.db import session_scope
from app.deps import _assert_tenant_active
from app.errors import ApiError
from app.metrics import assistant_socket_connections_total, assistant_socket_events_total
from app.models import AssistantRun, AssistantRunEvent, ChatConversation, ChatMessage, Tenant, User
from app.security import decode_access_token
from app.services.assistant_tool_runs import for_messages as tool_runs_for_messages
from app.services.queue import QUEUE_LLM, get_queue

logger = logging.getLogger(__name__)
_manager: socketio.AsyncRedisManager | None = None
_publisher: socketio.AsyncRedisManager | None = None
_dispatcher_task: asyncio.Task[None] | None = None
_expiry_tasks: dict[str, asyncio.Task[None]] = {}
_ephemeral_tasks: dict[str, tuple[str, UUID, asyncio.Task[None]]] = {}


def room_for(tenant_id: UUID, owner_id: UUID, conversation_id: UUID) -> str:
    return f"assistant:{tenant_id}:{owner_id}:{conversation_id}"


def manager() -> socketio.AsyncRedisManager:
    global _manager
    if _manager is None:
        _manager = socketio.AsyncRedisManager(get_settings().redis_url, channel="cbi-socketio")
    return _manager


def publisher() -> socketio.AsyncRedisManager:
    global _publisher
    if _publisher is None:
        _publisher = socketio.AsyncRedisManager(
            get_settings().redis_url, channel="cbi-socketio", write_only=True
        )
    return _publisher


async def authenticate(token: str) -> dict[str, Any]:
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise ApiError("unauthorized", "invalid token") from exc
    if claims.get("actor") != "user" or not claims.get("tenant_id"):
        raise ApiError("unauthorized", "tenant token required")
    tenant_id = UUID(str(claims["tenant_id"]))
    owner_id = UUID(str(claims["sub"]))
    async with session_scope(None, staff=True) as session:
        user = await session.get(User, owner_id)
        if user is None or user.tenant_id != tenant_id:
            raise ApiError("unauthorized", "user is unavailable")
    if user.role not in {"org_admin", "operator"}:
        raise ApiError("forbidden", "assistant access is restricted to operators")
    await _assert_tenant_active(tenant_id)
    return {
        "tenant_id": tenant_id,
        "owner_id": owner_id,
        "role": user.role,
        "expires_at": int(claims["exp"]),
    }


async def publish(
    tenant_id: UUID, run_id: UUID, event: str, payload: dict[str, Any]
) -> dict[str, Any]:
    async with session_scope(tenant_id) as session:
        run = await session.scalar(
            select(AssistantRun)
            .where(AssistantRun.id == run_id)
            .with_for_update()
        )
        if run is None:
            raise ApiError("not_found", "assistant run not found")
        if run.status in {"succeeded", "failed", "cancelled"} and event not in {
            "message:completed", "cancelled"
        }:
            return {}
        sequence = run.next_sequence
        run.next_sequence += 1
        run.last_event_sequence = sequence
        run.last_event_type = event
        run.last_event_payload = payload
        run.updated_at = datetime.now(UTC)
        session.add(
            AssistantRunEvent(run_id=run.id, sequence=sequence, event=event, payload=payload)
        )
        envelope = {
            "conversation_id": str(run.conversation_id),
            "run_id": str(run.id),
            "message_id": str(
                payload.get("message", {}).get("id") or run.user_message_id
            ),
            "user_message_id": str(run.user_message_id),
            "sequence": sequence,
            "event": event,
            "payload": payload,
            "tenant_id": str(run.tenant_id),
            "owner_id": str(run.owner_id),
        }
    room = room_for(
        UUID(envelope["tenant_id"]),
        UUID(envelope["owner_id"]),
        UUID(envelope["conversation_id"]),
    )
    await publisher().emit(f"assistant:{event}", envelope, room=room)
    assistant_socket_events_total.labels(event=event).inc()
    return envelope


sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=[],
    client_manager=manager(),
    ping_timeout=30,
    ping_interval=20,
    max_http_buffer_size=1_000_000,
)


@sio.event
async def connect(sid: str, environ: dict[str, Any], auth: dict[str, Any] | None = None) -> bool:
    token = (auth or {}).get("token")
    if not isinstance(token, str) or not token:
        return False
    try:
        identity = await authenticate(token)
    except Exception:
        assistant_socket_connections_total.labels(result="rejected").inc()
        return False
    await sio.save_session(sid, identity)
    assistant_socket_connections_total.labels(result="accepted").inc()

    async def expire_connection() -> None:
        await asyncio.sleep(max(0, identity["expires_at"] - time.time()))
        await sio.disconnect(sid)

    _expiry_tasks[sid] = asyncio.create_task(
        expire_connection(), name=f"assistant-socket-expiry-{sid}"
    )
    return True


@sio.event
async def disconnect(sid: str) -> None:
    task = _expiry_tasks.pop(sid, None)
    if task is not None and task is not asyncio.current_task():
        task.cancel()
    for owner_sid, _owner_id, ephemeral_task in list(_ephemeral_tasks.values()):
        if owner_sid == sid:
            ephemeral_task.cancel()


@sio.on("assistant:conversation:join")
async def join_conversation(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    identity = await sio.get_session(sid)
    try:
        conversation_id = UUID(str(data.get("conversation_id")))
        after_sequence = max(0, int(data.get("after_sequence", 0)))
    except (ValueError, TypeError):
        return {"ok": False, "code": "invalid_request"}
    tenant_id, owner_id = identity["tenant_id"], identity["owner_id"]
    room = room_for(tenant_id, owner_id, conversation_id)
    async with session_scope(tenant_id) as session:
        conversation = await session.get(ChatConversation, conversation_id)
        if (
            conversation is None
            or conversation.tenant_id != tenant_id
            or conversation.owner_id != owner_id
        ):
            return {"ok": False, "code": "not_found"}
        if conversation.mode == "training" and identity["role"] != "org_admin":
            return {"ok": False, "code": "forbidden"}
        await sio.enter_room(sid, room)
        messages = (
            (
                await session.execute(
                    select(ChatMessage)
                    .where(
                        ChatMessage.conversation_id == conversation_id,
                        ChatMessage.tenant_id == tenant_id,
                    )
                    .order_by(ChatMessage.ordinal)
                )
            )
            .scalars()
            .all()
        )
        tools_by_message = await tool_runs_for_messages(
            session, tenant_id, conversation_id,
            [row.id for row in messages if row.role == "assistant"],
        )
        active_runs = (
            (
                await session.execute(
                    select(AssistantRun)
                    .where(
                        AssistantRun.conversation_id == conversation_id,
                        AssistantRun.owner_id == owner_id,
                        AssistantRun.status.in_(("queued", "running")),
                        AssistantRun.assistant_message_id.is_(None),
                    )
                    .order_by(AssistantRun.created_at)
                )
            )
            .scalars()
            .all()
        )
        completed_runs = (
            (
                await session.execute(
                    select(AssistantRun)
                    .where(
                        AssistantRun.conversation_id == conversation_id,
                        AssistantRun.owner_id == owner_id,
                        AssistantRun.status.in_(("succeeded", "failed", "cancelled")),
                        AssistantRun.assistant_message_id.is_not(None),
                        AssistantRun.updated_at > datetime.now(UTC) - timedelta(hours=2),
                    )
                    .order_by(AssistantRun.updated_at.desc())
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        run_events: dict[str, list[dict[str, Any]]] = {}
        for run in active_runs:
            events = (
                (
                    await session.execute(
                        select(AssistantRunEvent)
                        .where(
                            AssistantRunEvent.run_id == run.id,
                            AssistantRunEvent.sequence > after_sequence,
                        )
                        .order_by(AssistantRunEvent.sequence)
                    )
                )
                .scalars()
                .all()
            )
            run_events[str(run.id)] = [
                {"sequence": row.sequence, "event": row.event, "payload": row.payload}
                for row in events
            ]
        latest = max((run.last_event_sequence for run in active_runs), default=0)
    state = {
        "ok": True,
        "conversation_id": str(conversation_id),
        "conversation": {
            "id": str(conversation.id),
            "title": conversation.title,
            "mode": conversation.mode,
        },
        "messages": [
            {
                "id": str(row.id),
                "role": row.role,
                "content": row.content,
                "status": row.status,
                "model": row.model,
                "sources": row.sources,
                "attachments": row.attachments,
                "tool_runs": tools_by_message.get(row.id, []),
                "created_at": row.created_at.isoformat(),
            }
            for row in messages
        ],
        "active_runs": [
            {
                "id": str(run.id),
                "user_message_id": str(run.user_message_id),
                "status": run.status,
                "sequence": run.last_event_sequence,
                "events": run_events[str(run.id)],
            }
            for run in active_runs
        ],
        "completed_runs": [
            {
                "id": str(run.id),
                "sequence": run.last_event_sequence,
                "message": {
                    "id": str(message.id),
                    "role": message.role,
                    "content": message.content,
                    "status": message.status,
                    "model": message.model,
                    "sources": message.sources,
                    "attachments": message.attachments,
                    "tool_runs": tools_by_message.get(message.id, []),
                    "memory_drafts": [],
                    "created_at": message.created_at.isoformat(),
                },
                "conversation_title": conversation.title,
            }
            for run in completed_runs
            if (message := next((item for item in messages if item.id == run.assistant_message_id), None))
        ],
        "sequence": latest,
    }
    await sio.emit("assistant:conversation:state", state, to=sid)
    for run in active_runs:
        if run.status == "queued":
            try:
                await get_queue().enqueue(
                    QUEUE_LLM,
                    "run_assistant_chat",
                    {"run_id": str(run.id), "tenant_id": str(tenant_id)},
                    job_id=f"assistant:{run.id}",
                )
            except Exception:
                logger.exception("could not ensure queued assistant run")
    return {"ok": True, "sequence": latest}


@sio.on("assistant:conversation:leave")
async def leave_conversation(sid: str, data: dict[str, Any]) -> dict[str, bool]:
    identity = await sio.get_session(sid)
    try:
        conversation_id = UUID(str(data.get("conversation_id")))
    except (ValueError, TypeError):
        return {"ok": False}
    await sio.leave_room(
        sid, room_for(identity["tenant_id"], identity["owner_id"], conversation_id)
    )
    return {"ok": True}


@sio.on("assistant:message:send")
async def send_message(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    identity = await sio.get_session(sid)
    try:
        conversation_id = UUID(str(data["conversation_id"]))
        idempotency_key = str(data["idempotency_key"])
        content = str(data["content"]).strip()
        request_id = str(data.get("request_id", ""))
        if not content or len(content) > 4000 or not idempotency_key or len(idempotency_key) > 128:
            raise ValueError
        attachments = data.get("attachments") or {}
    except (KeyError, ValueError, TypeError):
        return {"ok": False, "code": "invalid_request"}
    tenant_id, owner_id = identity["tenant_id"], identity["owner_id"]
    async with session_scope(tenant_id) as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": idempotency_key}
        )
        existing = (
            await session.execute(
                select(AssistantRun).where(
                    AssistantRun.tenant_id == tenant_id,
                    AssistantRun.owner_id == owner_id,
                    AssistantRun.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing:
            conversation_id = existing.conversation_id
            existing_message = await session.get(ChatMessage, existing.user_message_id)
            if existing_message is not None:
                content = existing_message.content
                attachments = existing_message.attachments or {}
            accepted = {
                "ok": True,
                "request_id": request_id,
                "conversation_id": str(conversation_id),
                "run_id": str(existing.id),
                "message_id": str(existing.user_message_id),
                "status": existing.status,
                "sequence": existing.last_event_sequence,
            }
        else:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"assistant-conversation:{conversation_id}"},
            )
            conversation = await session.get(ChatConversation, conversation_id)
            if (
                conversation is None
                or conversation.tenant_id != tenant_id
                or conversation.owner_id != owner_id
            ):
                return {"ok": False, "code": "not_found"}
            if conversation.mode == "training" and identity["role"] != "org_admin":
                return {"ok": False, "code": "forbidden"}
            from app.schemas import AssistantMessageAttachments

            try:
                validated_attachments = AssistantMessageAttachments.model_validate(attachments)
            except Exception:
                return {"ok": False, "code": "invalid_request"}
            active_run = (
                await session.execute(
                    select(AssistantRun)
                    .where(
                        AssistantRun.conversation_id == conversation_id,
                        AssistantRun.status.in_(("queued", "running")),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if active_run is not None:
                return {"ok": False, "code": "run_active", "run_id": str(active_run.id)}
            user_message = ChatMessage(
                conversation_id=conversation.id,
                tenant_id=tenant_id,
                role="user",
                content=content,
                attachments=validated_attachments.model_dump(mode="json"),
            )
            session.add(user_message)
            await session.flush()
            run = AssistantRun(
                tenant_id=tenant_id,
                owner_id=owner_id,
                conversation_id=conversation.id,
                user_message_id=user_message.id,
                idempotency_key=idempotency_key,
            )
            session.add(run)
            await session.flush()
            accepted = {
                "ok": True,
                "request_id": request_id,
                "conversation_id": str(conversation_id),
                "run_id": str(run.id),
                "message_id": str(user_message.id),
                "status": "queued",
                "sequence": 0,
            }
    room = room_for(tenant_id, owner_id, conversation_id)
    await sio.enter_room(sid, room)
    await sio.emit("assistant:message:accepted", accepted, to=sid)
    try:
        await get_queue().enqueue(
            QUEUE_LLM,
            "run_assistant_chat",
            {
                "run_id": accepted["run_id"],
                "tenant_id": str(tenant_id),
                "content": content,
                "attachments": attachments,
            },
            job_id=f"assistant:{accepted['run_id']}",
        )
    except Exception:
        logger.exception("failed to enqueue assistant run")
    return accepted


@sio.on("assistant:message:cancel")
async def cancel_message(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    identity = await sio.get_session(sid)
    try:
        run_id = UUID(str(data.get("run_id")))
    except (ValueError, TypeError):
        return {"ok": False, "code": "invalid_request"}
    async with session_scope(identity["tenant_id"]) as session:
        run = await session.scalar(
            select(AssistantRun)
            .where(AssistantRun.id == run_id)
            .with_for_update()
        )
        if run is None:
            ephemeral = _ephemeral_tasks.get(str(run_id))
            if ephemeral is None or ephemeral[0] != sid or ephemeral[1] != identity["owner_id"]:
                return {"ok": False, "code": "not_found"}
            ephemeral[2].cancel()
            return {"ok": True, "run_id": str(run_id)}
        if run.owner_id != identity["owner_id"]:
            return {"ok": False, "code": "not_found"}
        if run.status == "cancelled":
            return {"ok": True, "run_id": str(run_id)}
        if run.status not in {"queued", "running"}:
            return {"ok": False, "code": "already_finished"}
        cancelled_message = None
        if run.status in {"queued", "running"}:
            run.status = "cancelled"
            run.updated_at = datetime.now(UTC)
            message = ChatMessage(
                conversation_id=run.conversation_id,
                tenant_id=run.tenant_id,
                role="assistant",
                content="پاسخ متوقف شد.",
                status="cancelled",
                sources=[],
            )
            session.add(message)
            await session.flush()
            run.assistant_message_id = message.id
            from app.schemas import ChatMessageOut

            cancelled_message = ChatMessageOut.model_validate(message).model_dump(mode="json")
            conversation = await session.get(ChatConversation, run.conversation_id)
            if conversation is not None:
                conversation.updated_at = datetime.now(UTC)
    import redis.asyncio as redis

    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await client.setex(f"assistant:cancel:{run_id}", 3600, "1")
    finally:
        await client.aclose()
    await publish(
        identity["tenant_id"],
        run_id,
        "cancelled",
        {"status": "cancelled", "message": cancelled_message},
    )
    return {"ok": True, "run_id": str(run_id)}


@sio.on("assistant:ephemeral:send")
async def send_ephemeral(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    identity = await sio.get_session(sid)
    from app.deps import Principal
    from app.routers.assistant import stream_ephemeral_message
    from app.schemas import EphemeralChatMessageCreate

    try:
        content = str(data["content"]).strip()
        request_id = str(data.get("request_id", ""))
        if not content or len(content) > 4000:
            raise ValueError
        payload = EphemeralChatMessageCreate(
            content=content,
            attachments=data.get("attachments") or {},
            call_id=data.get("call_id"),
            history=data.get("history") or [],
        )
    except (KeyError, ValueError, TypeError):
        return {"ok": False, "code": "invalid_request"}
    ephemeral_id = UUID(hex=__import__("secrets").token_hex(16))
    principal = Principal(
        kind="user", id=identity["owner_id"], tenant_id=identity["tenant_id"], role=identity["role"]
    )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/assistant/ephemeral/socket",
        "raw_path": b"/v1/assistant/ephemeral/socket",
        "query_string": b"",
        "headers": [(b"x-forwarded-for", b"127.0.0.1")],
        "server": ("localhost", 8000),
        "client": ("127.0.0.1", 0),
        "root_path": "",
    }
    request = Request(scope)
    ack = {"ok": True, "request_id": request_id, "run_id": str(ephemeral_id), "status": "running"}
    await sio.emit("assistant:message:accepted", ack, to=sid)

    async def run() -> None:
        sequence = 0
        try:
            async with session_scope(identity["tenant_id"]) as session:
                response = await stream_ephemeral_message(payload, request, principal, session)
                buffer = ""
                async for chunk in response.body_iterator:
                    buffer += chunk.decode() if isinstance(chunk, bytes) else str(chunk)
                    frames = buffer.split("\n\n")
                    buffer = frames.pop()
                    for frame in frames:
                        event = next(
                            (
                                line[6:].strip()
                                for line in frame.splitlines()
                                if line.startswith("event:")
                            ),
                            None,
                        )
                        raw = "\n".join(
                            line[5:].lstrip()
                            for line in frame.splitlines()
                            if line.startswith("data:")
                        )
                        if not event or not raw:
                            continue
                        sequence += 1
                        envelope = {
                            "conversation_id": None,
                            "run_id": str(ephemeral_id),
                            "message_id": None,
                            "sequence": sequence,
                            "event": event,
                            "payload": json.loads(raw),
                        }
                        await sio.emit(f"assistant:{event}", envelope, to=sid)
        except asyncio.CancelledError:
            sequence += 1
            await sio.emit(
                "assistant:cancelled",
                {"conversation_id": None, "run_id": str(ephemeral_id), "sequence": sequence, "event": "cancelled", "payload": {"status": "cancelled"}},
                to=sid,
            )
            raise
        except Exception:
            logger.exception("ephemeral assistant socket run failed")
            await sio.emit(
                "assistant:error", {"run_id": str(ephemeral_id), "code": "assistant_failed"}, to=sid
            )
        finally:
            _ephemeral_tasks.pop(str(ephemeral_id), None)

    task = asyncio.create_task(run(), name=f"assistant-ephemeral-{ephemeral_id}")
    _ephemeral_tasks[str(ephemeral_id)] = (sid, identity["owner_id"], task)
    return ack


async def start() -> None:
    global _dispatcher_task
    if _dispatcher_task is None or _dispatcher_task.done():
        _dispatcher_task = asyncio.create_task(_dispatch_pending(), name="assistant-run-dispatcher")


async def _recover_stale_runs(tenant_id: UUID) -> list[tuple[UUID, dict[str, Any]]]:
    from app.schemas import ChatMessageOut

    recovered: list[tuple[UUID, dict[str, Any]]] = []
    cutoff = datetime.now(UTC) - timedelta(minutes=40)
    async with session_scope(tenant_id) as session:
        runs = (
            await session.execute(
                select(AssistantRun)
                .where(AssistantRun.status == "running", AssistantRun.updated_at < cutoff)
                .order_by(AssistantRun.updated_at)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for run in runs:
            message = ChatMessage(
                conversation_id=run.conversation_id,
                tenant_id=tenant_id,
                role="assistant",
                content="اجرای پاسخ به‌دلیل پایان زمان پردازش متوقف شد. لطفاً دوباره تلاش کنید.",
                status="failed",
                sources=[],
            )
            session.add(message)
            await session.flush()
            run.assistant_message_id = message.id
            run.status = "failed"
            run.updated_at = datetime.now(UTC)
            conversation = await session.get(ChatConversation, run.conversation_id)
            if conversation is not None:
                conversation.updated_at = datetime.now(UTC)
            recovered.append(
                (
                    run.id,
                    {
                        "message": ChatMessageOut.model_validate(message).model_dump(mode="json"),
                        "conversation_title": conversation.title if conversation else None,
                    },
                )
            )
    return recovered


async def _dispatch_pending() -> None:
    last_event_cleanup = 0.0
    while True:
        try:
            async with session_scope(None, staff=True) as session:
                tenant_ids = (
                    (await session.execute(select(Tenant.id).where(Tenant.status == "active")))
                    .scalars()
                    .all()
                )
            for tenant_id in tenant_ids:
                recovered = await _recover_stale_runs(tenant_id)
                async with session_scope(tenant_id) as session:
                    if time.time() - last_event_cleanup >= 300:
                        cutoff = datetime.now(UTC) - timedelta(
                            days=get_settings().assistant_event_retention_days
                        )
                        await session.execute(
                            delete(AssistantRunEvent).where(
                                AssistantRunEvent.created_at < cutoff
                            )
                        )
                    run_ids = (
                        (
                            await session.execute(
                                select(AssistantRun.id)
                                .where(AssistantRun.status == "queued")
                                .order_by(AssistantRun.created_at)
                                .limit(100)
                            )
                        )
                        .scalars()
                        .all()
                    )
                if time.time() - last_event_cleanup >= 300:
                    last_event_cleanup = time.time()
                for run_id, completion in recovered:
                    await publish(tenant_id, run_id, "message:completed", completion)
                for run_id in run_ids:
                    await get_queue().enqueue(
                        QUEUE_LLM,
                        "run_assistant_chat",
                        {"run_id": str(run_id), "tenant_id": str(tenant_id)},
                        job_id=f"assistant:{run_id}",
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("assistant run dispatch cycle failed")
        await asyncio.sleep(5)


async def close() -> None:
    global _dispatcher_task, _manager, _publisher
    tasks = [
        task
        for task in (
            _dispatcher_task,
            *tuple(_expiry_tasks.values()),
            *(entry[2] for entry in _ephemeral_tasks.values()),
        )
        if task is not None
    ]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _dispatcher_task = None
    _expiry_tasks.clear()
    _ephemeral_tasks.clear()
    for instance in (_manager, _publisher):
        if instance is None:
            continue
        thread = getattr(instance, "thread", None)
        if isinstance(thread, asyncio.Task) and not thread.done():
            thread.cancel()
            await asyncio.gather(thread, return_exceptions=True)
        pubsub = getattr(instance, "pubsub", None)
        if pubsub is not None:
            await pubsub.aclose()
        redis_client = getattr(instance, "redis", None)
        if redis_client is not None:
            await redis_client.aclose()
    _manager = None
    _publisher = None
