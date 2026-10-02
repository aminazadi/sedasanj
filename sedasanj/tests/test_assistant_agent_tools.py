import json

import pytest

from app.services import assistant_agent, assistant_tools
from worker_llm.client import LlmClient


class FakeClient(LlmClient):
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_object: bool = True,
        model: str | None = None,
    ) -> str:
        assert system
        assert "ابزارهای در دسترس" in user
        assert json_object
        assert model == "chat-model"
        return json.dumps(self.payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_agent_can_answer_without_a_tool() -> None:
    plan = await assistant_agent.plan(
        FakeClient({"answer": "سلام، چطور می‌توانم کمک کنم؟", "tool_calls": []}),
        "system",
        "سلام",
        "",
        model="chat-model",
    )
    assert plan.answer == "سلام، چطور می‌توانم کمک کنم؟"
    assert plan.tool_calls == []


@pytest.mark.asyncio
async def test_agent_validates_tool_arguments() -> None:
    plan = await assistant_agent.plan(
        FakeClient(
            {
                "answer": None,
                "tool_calls": [
                    {"name": "get_call_analytics", "arguments": {"status": "complete"}}
                ],
            }
        ),
        "system",
        "چند تماس داشتم؟",
        "",
        model="chat-model",
    )
    assert plan.tool_calls[0].name == "get_call_analytics"


@pytest.mark.asyncio
async def test_agent_rejects_disabled_tool() -> None:
    with pytest.raises(ValueError, match="disabled"):
        await assistant_agent.plan(
            FakeClient(
                {
                    "answer": None,
                    "tool_calls": [{"name": "search_calls", "arguments": {}}],
                }
            ),
            "system",
            "تماس‌ها را پیدا کن",
            "",
            model="chat-model",
            enabled={"get_call_analytics"},
        )


def test_tool_schemas_never_expose_security_scope() -> None:
    schemas = assistant_tools.schemas()
    assert len(schemas) == 6
    serialized = json.dumps(schemas)
    assert "tenant_id" not in serialized
    assert "user_id" not in serialized
    assert all(item["type"] == "function" for item in schemas)
