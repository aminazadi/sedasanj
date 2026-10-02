from __future__ import annotations

import json

import httpx

from app.config import Settings
from app.services.aiservice_decision import AiServiceDecisionClient


async def test_decision_client_appends_ninerouter_prompt_to_every_question() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen.update(json.loads(request.content))
            return httpx.Response(202, json={"task_id": "decision-1"})
        if request.url.path.endswith("/result"):
            return httpx.Response(
                200,
                json={"version": "v1", "answers": {"quality": {"answer": 1}}},
            )
        return httpx.Response(200, json={"status": "succeeded"})

    settings = Settings(
        environment="development",
        voicesanj_base_url="https://aiservice.example.test",
        voicesanj_api_key="test-key",
        decision_api_key="test-key",
        aiservice_decision_path="/v1/ninerouter/decisions",
        ninerouter_decision_prompt="فقط بر اساس شواهد تصمیم بگیر",
    )
    client = AiServiceDecisionClient(settings, request_namespace="test")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await client.decide(
            model="decision-model",
            state="sample",
            questions={
                "quality": {
                    "type": "score",
                    "instructions": "کیفیت را ارزیابی کن",
                    "criteria": ["ضعیف", "خوب"],
                },
                "resolved": {
                    "type": "noul",
                    "instructions": "حل مسئله را بررسی کن",
                },
            },
        )
    finally:
        await client.close()

    questions = seen["questions"]
    assert isinstance(questions, dict)
    assert questions["quality"]["instructions"] == (
        "کیفیت را ارزیابی کن\n\nفقط بر اساس شواهد تصمیم بگیر"
    )
    assert questions["resolved"]["instructions"] == (
        "حل مسئله را بررسی کن\n\nفقط بر اساس شواهد تصمیم بگیر"
    )
