import json
import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.routers import assistant
from app.schemas import AssistantMessageAttachments
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


class FakeTitleClient:
    async def complete(self, *args, **kwargs) -> str:
        return "«بررسی عملکرد اپراتور فروش»\nتوضیح اضافه"


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
async def test_conversation_title_is_generated_and_sanitized() -> None:
    title = await assistant._generate_conversation_title(
        FakeTitleClient(), "chat-model", "عملکرد اپراتور را بررسی کن", "پاسخ"
    )

    assert title == "بررسی عملکرد اپراتور فروش"


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
    assert len(schemas) == 9
    serialized = json.dumps(schemas)
    assert "tenant_id" not in serialized
    assert "user_id" not in serialized
    assert all(item["type"] == "function" for item in schemas)
    assert "get_current_time" in {item["function"]["name"] for item in schemas}
    chart_schema = next(
        item for item in schemas if item["function"]["name"] == "visualize_statistics"
    )
    assert chart_schema["function"]["parameters"]["properties"]["view"]["enum"] == [
        "call_status",
        "call_trend",
        "operator_performance",
    ]
    assert chart_schema["function"]["parameters"]["properties"]["chart_types"]["maxItems"] == 4
    chart_types = chart_schema["function"]["parameters"]["properties"]["chart_types"]
    assert set(chart_types["items"]["enum"]) == {
        "bar", "horizontal_bar", "line", "area", "pie", "donut", "radar",
        "radial_bar", "scatter", "composed", "treemap", "funnel",
    }


def test_current_time_tool_returns_utc_date_and_time() -> None:
    tool = assistant_tools.TOOL_BY_NAME["get_current_time"]
    result = asyncio.run(
        tool.executor(None, assistant_tools.CurrentTimeArguments())
    )
    instant = datetime.fromisoformat(result["datetime"])
    assert result["timezone"] == "UTC"
    assert instant.tzinfo == UTC
    assert result["date"] == instant.date().isoformat()
    assert result["time"] == instant.time().replace(microsecond=0).isoformat()
    assert result["unix_timestamp"] == int(instant.timestamp())


def test_current_time_is_available_with_legacy_explicit_tool_settings() -> None:
    settings = {"assistant_enabled_tools": json.dumps(["get_call_analytics"])}
    assert assistant._enabled_assistant_tools(settings) == {
        "get_current_time",
        "export_data",
        "get_call_analytics",
    }


def test_tool_preview_preserves_chart_payload() -> None:
    charts = [{"id": "status", "type": "donut", "data": []}]
    result = assistant_tools.preview({"total_calls": 3, "charts": charts})
    assert result["charts"] == charts


def test_final_response_only_retains_explicit_tool_backed_sources() -> None:
    selected = uuid4()
    ignored = uuid4()

    answer, call_ids = assistant_agent.final_response(
        f"پاسخ نهایی\n<call-sources>[\"{selected}\", \"{ignored}\", \"{selected}\"]</call-sources>",
        {str(selected)},
    )

    assert answer == "پاسخ نهایی"
    assert call_ids == [str(selected)]


def test_final_response_replaces_selected_call_ids_with_call_links() -> None:
    selected = uuid4()

    answer, call_ids = assistant_agent.final_response(
        f"جزئیات تماس {selected} را بررسی کردم.\n<call-sources>[\"{selected}\"]</call-sources>",
        {str(selected)},
    )

    assert answer == f"جزئیات تماس [مشاهده تماس](/calls/{selected}) را بررسی کردم."
    assert call_ids == [str(selected)]


def test_final_response_hides_invalid_or_missing_source_markers() -> None:
    answer, call_ids = assistant_agent.final_response(
        "پاسخ نهایی\n<call-sources>not-json</call-sources>", set()
    )

    assert answer == "پاسخ نهایی"
    assert call_ids == []


def test_result_call_ids_excludes_non_call_items() -> None:
    call_id = uuid4()
    results = [
        (
            assistant_agent.PlannedToolCall("tool-1", "search_calls", {}),
            {"items": [{"call_id": str(call_id)}, {"label": "not a call"}]},
        )
    ]

    assert assistant_agent.result_call_ids(results) == {str(call_id)}


def test_selected_context_overrides_model_tool_scope() -> None:
    operator_id = uuid4()
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 10, 1, tzinfo=UTC)
    plan = assistant_agent.AgentPlan(
        None,
        [
            assistant_agent.PlannedToolCall(
                "tool-1",
                "get_call_analytics",
                {"operator_id": str(uuid4()), "from_date": "2020-01-01T00:00:00Z"},
            )
        ],
    )
    attachments = AssistantMessageAttachments(
        operator_id=operator_id,
        from_date=start,
        to_date=end,
    )

    constrained = assistant._apply_attachment_constraints(plan, attachments)

    assert constrained.tool_calls[0].arguments["operator_id"] == str(operator_id)
    assert constrained.tool_calls[0].arguments["from_date"] == start.isoformat()
    assert constrained.tool_calls[0].arguments["to_date"] == end.isoformat()


def test_attached_tool_names_never_narrow_automatic_selection() -> None:
    settings = {"assistant_enabled_tools": json.dumps(["search_calls", "get_call_analysis"])}
    attachments = AssistantMessageAttachments(tool_names=["get_call_analysis"])

    assert assistant._attachment_tools(settings, attachments) == assistant._enabled_assistant_tools(
        settings
    )


def test_chat_message_output_preserves_attachments() -> None:
    attachments = AssistantMessageAttachments(
        operator_id=uuid4(),
        conversation_ids=[uuid4()],
        from_date=datetime(2026, 9, 1, tzinfo=UTC),
        to_date=datetime(2026, 10, 1, tzinfo=UTC),
        tool_names=["get_call_analysis"],
    )
    payload = attachments.model_dump(mode="json")

    assert AssistantMessageAttachments.model_validate(payload) == attachments


@pytest.mark.asyncio
async def test_operator_mentions_are_rejected_for_non_admin_users() -> None:
    principal = SimpleNamespace(id=uuid4(), role="operator")
    attachments = AssistantMessageAttachments(operator_id=uuid4())

    with pytest.raises(ApiError):
        await assistant._attachment_context(
            object(), uuid4(), principal.id, principal, attachments
        )
