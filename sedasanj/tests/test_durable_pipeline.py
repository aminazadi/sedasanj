from __future__ import annotations

import json
from uuid import uuid4

import httpx

from app.config import Settings
from app.services import outbox, queue
from worker_llm.client import VoiceSanjChatClient
from worker_llm.durable import _step_key


def _settings() -> Settings:
    return Settings(
        environment="development",
        llm_client="voicesanj",
        voicesanj_base_url="http://provider.test",
        voicesanj_api_key="secret",
        voicesanj_llm_model="model",
        worker_metrics_port=0,
    )


def test_outbox_payload_preserves_llm_recovery_context() -> None:
    call_id = uuid4()
    run_id = uuid4()
    queue_name, function_name, payload = outbox.payload_for_job(
        "llm",
        call_id,
        analysis_run_id=run_id,
        recovery=True,
        reanalysis=True,
        previous_status="failed_terminal",
    )

    assert queue_name == queue.QUEUE_LLM
    assert function_name == queue.JOB_LLM
    assert payload == {
        "call_id": str(call_id),
        "analysis_run_id": str(run_id),
        "reanalysis": True,
        "previous_status": "failed_terminal",
        "recovery": True,
    }


def test_analysis_step_idempotency_is_stable_and_input_specific() -> None:
    run_id = uuid4()
    first = _step_key(run_id, "extract", 0, "متن اول")
    repeated = _step_key(run_id, "extract", 0, "متن اول")
    changed = _step_key(run_id, "extract", 0, "متن دوم")

    assert first == repeated
    assert first != changed
    assert first[1].startswith("cbi-analysis-")


async def test_voicesanj_submit_returns_without_polling() -> None:
    paths: list[str] = []
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        bodies.append(json.loads(request.content))
        assert request.headers["Idempotency-Key"] == "stable-key"
        return httpx.Response(202, json={"task_id": "task-1", "status": "queued"})

    client = VoiceSanjChatClient(_settings(), request_namespace="run-1")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        task_id = await client.submit(
            "system",
            "user",
            model="model",
            idempotency_key="stable-key",
        )
    finally:
        await client.close()

    assert task_id == "task-1"
    assert paths == ["/v1/chat/tasks"]
    assert bodies[0]["model"] == "model"
