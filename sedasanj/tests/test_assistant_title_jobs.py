from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from arq import Retry

from app.models import ChatConversation, ChatMessage
from app.routers import assistant
from app.services import assistant_agent, queue
from worker_llm import main as worker
from worker_llm.main import AssistantWorkerSettings, WorkerSettings, generate_assistant_title


@pytest.mark.parametrize(
    "title,status,queued",
    [(None, "succeeded", True), ("Manual", "succeeded", False), (None, "failed", False)],
)
async def test_title_job_only_for_successful_untitled_conversations(
    monkeypatch: pytest.MonkeyPatch, title: str | None, status: str, queued: bool
) -> None:
    tenant_id, owner_id, conversation_id = uuid4(), uuid4(), uuid4()
    conversation = ChatConversation(
        id=conversation_id,
        tenant_id=tenant_id,
        owner_id=owner_id,
        title=title,
        updated_at=datetime.now(UTC),
    )
    question = ChatMessage(id=uuid4(), role="user", content="Private question")
    answer = ChatMessage(id=uuid4(), role="assistant", content="Private answer", status=status)
    stage = AsyncMock()
    monkeypatch.setattr(assistant.outbox, "stage", stage)
    await assistant._queue_conversation_title(AsyncMock(), conversation, question, answer)
    assert stage.await_count == int(queued)
    if queued:
        assert stage.call_args.kwargs["queue_name"] == queue.QUEUE_LLM
        assert stage.call_args.kwargs["payload"] == {
            "tenant_id": str(tenant_id),
            "owner_id": str(owner_id),
            "conversation_id": str(conversation_id),
            "version": conversation.updated_at.isoformat(),
            "question_id": str(question.id),
            "answer_id": str(answer.id),
        }


def test_title_jobs_do_not_occupy_interactive_worker() -> None:
    assert generate_assistant_title in WorkerSettings.functions
    assert generate_assistant_title not in AssistantWorkerSettings.functions


def test_read_only_batches_keep_order_and_isolate_export() -> None:
    calls = [
        assistant_agent.PlannedToolCall(str(index), name, {})
        for index, name in enumerate(
            ("search_calls", "get_call_analysis", "search_calls", "export_data", "search_knowledge")
        )
    ]
    batches = list(assistant._planned_tool_batches(calls, {"assistant_parallel_tools": "2"}))
    assert [[call.id for call in batch] for batch in batches] == [["0", "1"], ["3"], ["4"]]


async def test_parallel_tools_preserve_success_when_a_peer_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = assistant_agent.PlannedToolCall("a", "search_calls", {})
    second = assistant_agent.PlannedToolCall("b", "search_knowledge", {})
    started = asyncio.Event()
    failure = TimeoutError("search unavailable")

    async def execute(call, *_):
        if call == first:
            await asyncio.wait_for(started.wait(), timeout=2)
            return {"items": ["one"]}, 1
        started.set()
        raise failure

    monkeypatch.setattr(assistant, "_execute_planned_tool", execute)
    outcomes = await assistant._run_tool_batch([first, second], object(), None, None)
    assert outcomes == [({"items": ["one"]}, 1), failure]


async def test_dedicated_queue_defers_a_tenant_with_an_active_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = AsyncMock()
    database.scalar.return_value = False

    @asynccontextmanager
    async def control():
        yield database

    run = AsyncMock(return_value="succeeded")
    monkeypatch.setattr(worker, "control_session_scope", control)
    monkeypatch.setattr(worker, "_run_assistant_chat", run)
    payload = {"tenant_id": str(uuid4()), "run_id": str(uuid4())}
    with pytest.raises(Retry):
        await worker.run_assistant_chat({"assistant_dedicated_worker": True}, payload)
    run.assert_not_called()
    database.scalar.return_value = True
    assert (
        await worker.run_assistant_chat({"assistant_dedicated_worker": True}, payload)
        == "succeeded"
    )
