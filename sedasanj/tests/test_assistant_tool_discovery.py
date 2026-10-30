from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.routers import assistant
from app.schemas import AssistantMessageAttachments, SettingsUpdate
from app.services import assistant_agent, assistant_tools
from app.services import assistant_tool_catalog as catalog
from app.services.provider_errors import ProviderError
from worker_llm.client import LlmClient


class PlannerClient(LlmClient):
    def __init__(self, responses, *, native=False, native_error=None):
        self.responses = list(responses)
        self.native = native
        self.native_error = native_error
        self.prompts = []
        self.definitions = []
        self.native_requests = 0

    async def complete(self, system, user, *, json_object=True, model=None):
        self.prompts.append(user)
        return json.dumps(self.responses.pop(0), ensure_ascii=False)

    async def complete_with_tools(self, system, user, tools, *, model=None):
        self.native_requests += 1
        self.prompts.append(user)
        self.definitions.append(tools)
        if self.native_error:
            raise self.native_error
        if not self.native:
            return await super().complete_with_tools(system, user, tools, model=model)
        response = self.responses.pop(0)
        return {
            "content": response.get("answer"),
            "tool_calls": [
                {
                    "id": f"native-{index}",
                    "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call["arguments"])},
                }
                for index, call in enumerate(response.get("tool_calls", []))
            ],
        }


def tool_plan(*calls):
    return {
        "answer": None,
        "tool_calls": [{"name": name, "arguments": args} for name, args in calls],
    }


@pytest.mark.parametrize("query", ["فایل اکسل", "export excel", "خروجي فایل", "پی دی اف"])
def test_catalog_finds_export_in_persian_and_english(query):
    result = catalog.search(catalog.SearchArguments(query=query), None)
    assert result["items"][0]["name"] == "export_data"
    assert "dataset" in result["items"][0]["parameters"]["required"]
    assert "format" in result["items"][0]["parameters"]["required"]


def test_catalog_never_exposes_disabled_tools():
    result = catalog.search(catalog.SearchArguments(query="فایل export excel"), {"search_calls"})
    assert result == {"count": 0, "items": []}
    assert catalog.search(catalog.SearchArguments(query="تماس"), set())["items"] == []


@pytest.mark.parametrize("native", [False, True])
async def test_assistant_discovers_then_selects_multiple_tools_without_manual_selection(native):
    client = PlannerClient(
        [
            tool_plan(("search_tools", {"query": "آمار خروجی اکسل", "limit": 5})),
            tool_plan(
                ("get_call_analytics", {}),
                ("export_data", {"dataset": "calls_analysis", "format": "xlsx"}),
            ),
        ],
        native=native,
    )
    plan = await assistant_agent.plan(
        client,
        "system",
        "آمار و فایل اکسل تماس‌ها را بده",
        "",
        model="model",
        mode="native" if native else "structured",
    )
    assert [call.name for call in plan.tool_calls] == ["get_call_analytics", "export_data"]
    assert "نتایج جست‌وجوی فهرست ابزارها" in client.prompts[-1]
    assert "export_data" in client.prompts[-1]
    if native:
        assert client.native_requests == 2
        assert "search_tools" in {tool["function"]["name"] for tool in client.definitions[0]}


async def test_direct_selection_can_use_multiple_tools_without_discovery():
    client = PlannerClient([tool_plan(("search_calls", {}), ("get_call_analytics", {}))])
    plan = await assistant_agent.plan(
        client,
        "system",
        "تماس و آمار را بده",
        "",
        model="model",
        mode="structured",
        discovery_rounds=0,
    )
    assert len(plan.tool_calls) == 2
    assert '"name": "search_tools"' not in client.prompts[0]


async def test_discovery_is_bounded_and_disabled_on_final_round():
    client = PlannerClient(
        [
            tool_plan(("search_tools", {"query": "فایل"})),
            tool_plan(("search_tools", {"query": "اکسل"})),
            tool_plan(("export_data", {"dataset": "calls_analysis", "format": "xlsx"})),
        ],
        native=True,
    )
    plan = await assistant_agent.plan(
        client, "system", "خروجی بده", "", model="model", mode="native"
    )
    assert plan.tool_calls[0].name == "export_data"
    assert len(client.definitions) == 3
    assert "search_tools" not in {tool["function"]["name"] for tool in client.definitions[-1]}


async def test_training_has_no_discovery_or_native_tools():
    client = PlannerClient([{"answer": "دانش سازمان را توضیح دهید", "tool_calls": []}], native=True)
    plan = await assistant_agent.plan(client, "system", "آموزش", "", model="model", enabled=set())
    assert not plan.tool_calls
    assert client.native_requests == 0
    assert '"name": "search_tools"' not in client.prompts[0]


async def test_discovery_cannot_enable_a_disallowed_tool():
    client = PlannerClient(
        [
            tool_plan(("search_tools", {"query": "فایل"})),
            tool_plan(("export_data", {"dataset": "contacts", "format": "csv"})),
        ]
    )
    with pytest.raises(ValueError, match="disabled"):
        await assistant_agent.plan(
            client,
            "system",
            "خروجی بده",
            "",
            model="model",
            enabled={"search_calls"},
            mode="structured",
        )
    assert '"name": "export_data"' not in client.prompts[-1]


async def test_native_schema_rejection_falls_back_to_json_planning():
    client = PlannerClient(
        [
            tool_plan(("export_data", {"dataset": "calls_analysis", "format": "xlsx"})),
        ],
        native_error=ProviderError(
            "llm_provider_request", "tool schema unsupported", retryable=False
        ),
    )
    plan = await assistant_agent.plan(
        client, "system", "فایل اکسل بده", "", model="model", mode="native"
    )
    assert plan.tool_calls[0].name == "export_data"
    assert client.native_requests == 1


async def test_native_auth_failure_does_not_fall_back_in_native_mode():
    client = PlannerClient(
        [], native_error=ProviderError("llm_provider_auth", "auth failed", retryable=False)
    )
    with pytest.raises(ProviderError) as error:
        await assistant_agent.plan(client, "system", "فایل بده", "", model="model", mode="native")
    assert error.value.code == "llm_provider_auth"
    assert len(client.prompts) == 1


async def test_missing_export_arguments_prompt_for_clarification_instead_of_generic_failure():
    client = PlannerClient(
        [
            tool_plan(("export_data", {})),
            {"answer": "کدام دسته داده را در چه قالبی می‌خواهید؟", "tool_calls": []},
        ]
    )
    plan = await assistant_agent.plan(
        client,
        "system",
        "لطفاً انجامش بده",
        "",
        model="model",
        enabled={"export_data"},
        mode="structured",
    )
    assert not plan.tool_calls
    assert "قالب" in plan.answer
    assert "dataset" in client.prompts[-1]
    assert "format" in client.prompts[-1]


async def test_argument_repair_never_echoes_submitted_values():
    secret = "never-echo-this-test-value"
    client = PlannerClient(
        [
            tool_plan(("export_data", {"dataset": secret, "format": "xlsx"})),
            tool_plan(("export_data", {"dataset": "calls_analysis", "format": "xlsx"})),
        ]
    )
    plan = await assistant_agent.plan(
        client, "system", "خروجی اکسل تماس بده", "", model="model", mode="structured"
    )
    assert plan.tool_calls[0].arguments["dataset"] == "calls_analysis"
    assert secret not in client.prompts[-1]


async def test_repeated_invalid_export_arguments_have_an_actionable_error_code():
    client = PlannerClient([tool_plan(("export_data", {})), tool_plan(("export_data", {}))])
    with pytest.raises(ApiError) as error:
        await assistant_agent.plan(
            client, "system", "خروجی بده", "", model="model", mode="structured"
        )
    assert error.value.code == "assistant_tool_plan_invalid"
    assert "دسته داده" in assistant._assistant_error(error.value)
    assert "سرویس هوش مصنوعی آماده نشد" not in assistant._assistant_error(error.value)


def test_stale_selected_export_has_specific_error_instead_of_invalid_request():
    with pytest.raises(ApiError) as error:
        assistant._attachment_tools(
            {"assistant_enabled_tools": json.dumps(["search_calls"])},
            AssistantMessageAttachments(tool_names=["export_data"]),
        )
    assert error.value.code == "assistant_tool_disabled"
    assert "تنظیمات" in assistant._assistant_error(error.value)


async def test_context_options_only_offer_enabled_tools(monkeypatch):
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: []),
            )
        )
    )
    monkeypatch.setattr(
        assistant,
        "effective_models",
        AsyncMock(
            return_value={
                "assistant_enabled_tools": json.dumps(["get_call_analytics"]),
            }
        ),
    )
    response = await assistant.assistant_context_options(
        SimpleNamespace(tenant_id=uuid4(), id=uuid4(), role="operator"),
        session,
    )
    assert {tool["name"] for tool in response["tools"]} == {
        "get_call_analytics",
        "get_current_time",
    }


def test_discovery_budget_is_admin_validated():
    assert SettingsUpdate(assistant_max_discovery_rounds=0).assistant_max_discovery_rounds == 0
    with pytest.raises(ValueError):
        SettingsUpdate(assistant_max_discovery_rounds=3)


async def test_discovery_uses_unique_local_call_ids_and_deduplicates_requested_tools():
    client = PlannerClient(
        [
            tool_plan(("get_call_analytics", {}), ("search_tools", {"query": "اکسل"})),
            tool_plan(
                ("get_call_analytics", {}),
                ("export_data", {"dataset": "calls_analysis", "format": "xlsx"}),
            ),
        ],
        native=True,
    )
    plan = await assistant_agent.plan(
        client, "system", "آمار و اکسل بده", "", model="model", mode="native"
    )
    assert [call.name for call in plan.tool_calls] == ["get_call_analytics", "export_data"]
    assert len({call.id for call in plan.tool_calls}) == 2


@pytest.mark.parametrize("native", [False, True])
async def test_selected_file_tool_runs_after_planning_with_date_scope(monkeypatch, native):
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime

    from app.deps import Principal
    from app.services import assistant_exports as exports
    from app.services.storage import MemoryStorage

    principal = Principal(kind="user", id=uuid4(), tenant_id=uuid4(), role="operator")
    attachments = AssistantMessageAttachments(
        tool_names=["export_data"],
        from_date=datetime(2026, 10, 28, tzinfo=UTC),
        to_date=datetime(2026, 10, 30, tzinfo=UTC),
    )
    settings = {"assistant_enabled_tools": json.dumps(["export_data"])}
    client = PlannerClient(
        [
            tool_plan(("search_tools", {"query": "فایل اکسل"})),
            tool_plan(("export_data", {"dataset": "calls_analysis", "format": "xlsx"})),
        ],
        native=native,
    )
    plan = await assistant_agent.plan(
        client,
        "system",
        "لطفاً انجامش بده",
        "خروجی اکسل تماس‌های بازه انتخاب‌شده را می‌خواهم",
        model="model",
        enabled=assistant._attachment_tools(settings, attachments),
        mode="native" if native else "structured",
    )
    plan = assistant._apply_attachment_constraints(plan, attachments)
    store = MemoryStorage()
    loader = AsyncMock(return_value=[{"call_id": str(uuid4()), "summary": "خلاصه آزمایشی"}])
    monkeypatch.setattr(exports, "get_storage", lambda: store)
    monkeypatch.setattr(exports, "load_rows", loader)
    monkeypatch.setattr(exports.platform, "effective_models", AsyncMock(return_value={}))
    monkeypatch.setattr(exports.ratelimit, "enforce", AsyncMock())
    monkeypatch.setattr(exports.audit, "record", AsyncMock())

    class Session:
        def add(self, row):
            self.row = row

        async def flush(self):
            pass

        @asynccontextmanager
        async def begin_nested(self):
            yield

    session = Session()
    planned = plan.tool_calls[0]
    result, duration = await assistant_tools.execute(
        planned.name,
        planned.arguments,
        assistant_tools.ToolContext(session, principal, None),
    )
    assert result["file"]["format"] == "xlsx"
    assert result["file"]["rows"] == 1
    assert store.objects[session.row.storage_key].startswith(b"PK")
    assert loader.call_args.args[3].from_date == attachments.from_date
    assert loader.call_args.args[3].to_date == attachments.to_date
    answer, _ = assistant_agent.final_response("فایل آماده شد", set(), [(planned, result)])
    assert result["notice"] in answer
    assert duration >= 0


async def test_native_provider_can_return_a_structured_plan_as_text():
    class TextPlanClient(PlannerClient):
        async def complete_with_tools(self, *args, **kwargs):
            return {
                "content": json.dumps(
                    tool_plan(("export_data", {"dataset": "calls_analysis", "format": "xlsx"}))
                ),
                "tool_calls": [],
            }

    plan = await assistant_agent.plan(
        TextPlanClient([]), "system", "اکسل تماس‌ها را بده", "", model="model", mode="native"
    )
    assert [call.name for call in plan.tool_calls] == ["export_data"]


def test_discovery_help_articles_map_actionable_error_codes():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts/seed_help_articles.py"
    spec = importlib.util.spec_from_file_location("tool_discovery_help", path)
    assert spec and spec.loader
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    articles = {slug: (codes, html) for slug, _title, codes, html in seed.ARTICLES}
    assert "assistant-tool-discovery" in articles
    for slug, code in [
        ("assistant-tool-disabled", "assistant_tool_disabled"),
        ("assistant-tool-plan-invalid", "assistant_tool_plan_invalid"),
        ("assistant-export-unavailable", "assistant_export_unavailable"),
    ]:
        codes, html = articles[slug]
        assert code in codes
        for heading in ["علائم", "علت", "راه‌حل", "چطور مطمئن شوم درست شد؟", "پیشگیری"]:
            assert heading in html


async def test_native_missing_export_fields_can_recover_with_a_clarifying_question():
    client = PlannerClient(
        [
            tool_plan(("export_data", {})),
            {"answer": "کدام دسته داده و کدام قالب فایل را می‌خواهید؟", "tool_calls": []},
        ],
        native=True,
    )
    plan = await assistant_agent.plan(
        client,
        "system",
        "لطفاً انجامش بده",
        "",
        model="model",
        mode="native",
    )
    assert not plan.tool_calls
    assert "قالب" in plan.answer
    assert client.native_requests == 1
