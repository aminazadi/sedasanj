from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest

from app.services import ai_usage
from app.services.ai_usage import ai_feature, extract_usage, record_usage, usage_dict


def test_extract_openai_shape() -> None:
    usage = extract_usage({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (10, 5, 15)
    assert usage.source == "reported"


def test_extract_input_output_shape_derives_total() -> None:
    usage = extract_usage({"input_tokens": 7, "output_tokens": 3})
    assert usage.total_tokens == 10
    assert usage.source == "reported"


@pytest.mark.parametrize("raw", [None, {}, "x", {"prompt_tokens": 4}, {"prompt_tokens": True}])
def test_missing_usage_is_unavailable_never_zero(raw: object) -> None:
    usage = extract_usage(raw)
    assert usage.source == "unavailable"
    assert usage.completion_tokens is None


def test_negative_counts_are_rejected() -> None:
    usage = extract_usage({"prompt_tokens": -1, "completion_tokens": 2})
    assert usage.source == "unavailable"


def test_embedding_reports_input_only() -> None:
    usage = extract_usage({"prompt_tokens": 9}, output_optional=True)
    assert (usage.completion_tokens, usage.total_tokens, usage.source) == (0, 9, "reported")


def test_usage_dict() -> None:
    assert usage_dict({"a": 1}) == {"a": 1}
    assert usage_dict(None) == {}


class _Session:
    def __init__(self, sink: list[Any]) -> None:
        self.sink = sink

    async def execute(self, statement: Any) -> None:
        self.sink.append(statement)


def _patch_scope(monkeypatch: pytest.MonkeyPatch, sink: list[Any]) -> None:
    @asynccontextmanager
    async def scope(tenant_id: Any = None, **_: Any):  # type: ignore[no-untyped-def]
        yield _Session(sink)

    monkeypatch.setattr(ai_usage, "session_scope", scope)


async def test_record_usage_writes_one_row(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: list[Any] = []
    _patch_scope(monkeypatch, sink)
    await record_usage(
        {"prompt_tokens": 2, "completion_tokens": 3},
        provider="aiservice",
        model="m",
        origin="local",
        provider_task_id="t1",
        tenant_id=uuid4(),
    )
    assert len(sink) == 1
    compiled = sink[0].compile()
    assert compiled.params["dedupe_key"] == "aiservice:t1"
    assert compiled.params["usage_source"] == "reported"
    assert compiled.params["feature"] == "llm"


async def test_feature_label_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: list[Any] = []
    _patch_scope(monkeypatch, sink)
    with ai_feature("analysis"):
        await record_usage(None, provider="p", model=None, tenant_id=uuid4())
    params = sink[0].compile().params
    assert params["feature"] == "analysis"
    assert params["usage_source"] == "unavailable"


async def test_no_tenant_skips_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: list[Any] = []
    _patch_scope(monkeypatch, sink)
    await record_usage({"prompt_tokens": 1, "completion_tokens": 1}, provider="p", model=None)
    assert sink == []


async def test_write_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def boom(*_: Any, **__: Any):  # type: ignore[no-untyped-def]
        raise RuntimeError("db down")
        yield

    monkeypatch.setattr(ai_usage, "session_scope", boom)
    await record_usage(None, provider="p", model=None, tenant_id=uuid4())


async def test_set_ai_feature_labels_the_current_task(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    sink: list[Any] = []
    _patch_scope(monkeypatch, sink)

    async def job() -> None:
        ai_usage.set_ai_feature("coach")
        await record_usage(None, provider="p", model=None, tenant_id=uuid4())

    await asyncio.create_task(job())
    assert sink[0].compile().params["feature"] == "coach"
    # a sibling task keeps the default: labels never leak across tasks
    await asyncio.create_task(record_usage(None, provider="p", model=None, tenant_id=uuid4()))
    assert sink[1].compile().params["feature"] == "llm"
