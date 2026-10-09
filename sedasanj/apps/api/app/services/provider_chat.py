from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from typing import Any

import httpx

from app.services.provider_errors import ProviderError, inspect_payload


def _invalid(detail: str = "قالب پاسخ مدل نامعتبر است.") -> ProviderError:
    return ProviderError("llm_provider_response", detail, retryable=False)


def content_text(value: Any) -> str:
    """Extract public text blocks only; never expose reasoning or tool arguments."""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts = []
    for item in value:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in {"text", "output_text", "refusal"}:
            continue
        text = item.get("text") if item.get("type") != "refusal" else item.get("refusal")
        if isinstance(text, dict):
            text = text.get("value")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def chat_message(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and any(
        payload.get(key) for key in ("error", "error_code", "code")
    ):
        inspect_payload(payload, kind="llm")
    if not isinstance(payload, dict) or payload.get("error"):
        raise _invalid()
    if payload.get("status") in {"failed", "incomplete", "cancelled", "in_progress", "queued"}:
        raise _invalid("پاسخ مدل کامل نشده است.")
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        choice = choices[0]
        if choice.get("finish_reason") in {"length", "content_filter"}:
            raise _invalid("پاسخ مدل به‌دلیل محدودیت خروجی کامل نشد.")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise _invalid()
        message = dict(message)
        message["content"] = content_text(message.get("content")) or content_text(
            message.get("refusal")
        )
        if not message.get("tool_calls") and isinstance(message.get("function_call"), dict):
            message["tool_calls"] = [
                {"id": "legacy-function", "type": "function", "function": message["function_call"]}
            ]
    elif isinstance(payload.get("output"), list):
        texts, calls = [], []
        for item in payload["output"]:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message" and item.get("role", "assistant") == "assistant":
                texts.append(content_text(item.get("content")))
            elif item.get("type") == "function_call":
                calls.append(
                    {
                        "id": item.get("call_id") or item.get("id"),
                        "type": "function",
                        "function": {
                            "name": item.get("name"),
                            "arguments": item.get("arguments", ""),
                        },
                    }
                )
        message = {
            "content": "".join(texts) or content_text(payload.get("output_text")),
            "tool_calls": calls,
        }
    else:
        raise _invalid()
    calls = message.get("tool_calls") or []
    if not isinstance(calls, list) or any(not isinstance(call, dict) for call in calls):
        raise _invalid("فراخوانی ابزار مدل نامعتبر است.")
    if not message["content"].strip() and not calls:
        raise _invalid("مدل متن یا فراخوانی ابزار قابل استفاده‌ای برنگرداند.")
    return message


class ChatStream:
    """Normalize Chat Completions and Responses SSE into one assistant message."""

    def __init__(self) -> None:
        self.text = ""
        self.tools: dict[int, dict[str, Any]] = {}
        self.finished = False
        self.terminal = False
        self.usage: dict[str, Any] = {}

    def _snapshot(self, message: dict[str, Any]) -> str:
        text = message["content"]
        if self.text and not text.startswith(self.text):
            raise _invalid("متن نهایی مدل با جریان پاسخ سازگار نیست.")
        delta = text[len(self.text) :]
        self.text = text
        self.tools = dict(enumerate(message.get("tool_calls") or []))
        return delta

    def feed(self, event: str, raw: str) -> str:
        if raw.strip() == "[DONE]":
            self.terminal = True
            self.finished = True
            return ""
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise _invalid() from exc
        if not isinstance(payload, dict):
            raise _invalid()
        if any(payload.get(key) for key in ("error", "error_code", "code")):
            inspect_payload(payload, kind="llm")
        kind = payload.get("type") or event
        if payload.get("error") or kind in {"error", "response.failed", "response.incomplete"}:
            raise _invalid("مدل خطا یا پاسخ ناقص برگرداند.")
        if isinstance(payload.get("usage"), dict):
            self.usage = payload["usage"]
        if kind == "response.completed":
            final = payload.get("response")
            delta = self._snapshot(chat_message(final))
            self.finished = True
            self.terminal = True
            if isinstance(final.get("usage"), dict):
                self.usage = final["usage"]
            return delta
        if kind in {"response.output_text.delta", "response.refusal.delta"}:
            delta = payload.get("delta")
            if not isinstance(delta, str):
                raise _invalid()
            self.text += delta
            return delta
        if isinstance(kind, str) and kind.startswith("response."):
            # Responses carries the authoritative tool calls in response.completed.
            return ""
        if payload.get("object") == "response" or isinstance(payload.get("output"), list):
            delta = self._snapshot(chat_message(payload))
            self.finished = True
            return delta
        choices = payload.get("choices")
        if choices == [] and isinstance(payload.get("usage"), dict):
            return ""
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise _invalid()
        choice = choices[0]
        if choice.get("finish_reason") in {"length", "content_filter"}:
            raise _invalid("پاسخ مدل به‌دلیل محدودیت خروجی کامل نشد.")
        self.finished = self.finished or choice.get("finish_reason") in {
            "stop",
            "tool_calls",
            "function_call",
        }
        if isinstance(choice.get("message"), dict):
            return self._snapshot(chat_message(payload))
        delta = choice.get("delta", {})
        if delta is None and self.finished:
            delta = {}
        if not isinstance(delta, dict):
            raise _invalid()
        text = content_text(delta.get("content")) or content_text(delta.get("refusal"))
        self.text += text
        calls = delta.get("tool_calls") or []
        if isinstance(delta.get("function_call"), dict):
            calls = [{"index": 0, "id": "legacy-function", "function": delta["function_call"]}]
        if not isinstance(calls, list):
            raise _invalid()
        for call in calls:
            if not isinstance(call, dict):
                raise _invalid()
            index = call.get("index", 0)
            if not isinstance(index, int) or index < 0:
                raise _invalid()
            target = self.tools.setdefault(
                index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
            )
            if call.get("id"):
                target["id"] = call["id"]
            function = call.get("function") or {}
            if not isinstance(function, dict):
                raise _invalid()
            for field in ("name", "arguments"):
                piece = function.get(field)
                if piece is not None:
                    if not isinstance(piece, str):
                        raise _invalid()
                    target["function"][field] += piece
        return text

    def result(self) -> dict[str, Any]:
        if not self.finished:
            raise ProviderError(
                "llm_provider_stream_interrupted",
                "جریان پاسخ مدل پیش از تکمیل قطع شد.",
                retryable=True,
            )
        payload = {
            "choices": [
                {
                    "message": {
                        "content": self.text,
                        "tool_calls": [self.tools[key] for key in sorted(self.tools)],
                    }
                }
            ],
            "usage": self.usage,
        }
        chat_message(payload)
        return payload


def _frame(lines: Iterable[str]) -> tuple[str, str]:
    event = ""
    data = []
    for line in lines:
        if line.startswith("event:"):
            event = line[6:].lstrip(" ")
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    return event, "\n".join(data)


async def sse_frames(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, str]]:
    pending = []
    async for line in lines:
        if not line:
            event, data = _frame(pending)
            pending = []
            if data:
                yield event, data
        else:
            pending.append(line)
    if pending:
        event, data = _frame(pending)
        if data:
            yield event, data


async def stream_chat(response: httpx.Response, state: ChatStream) -> AsyncIterator[str]:
    if "application/json" in response.headers.get("content-type", "").lower():
        await response.aread()
        try:
            payload = response.json()
            message = chat_message(payload)
            if isinstance(payload.get("usage"), dict):
                state.usage = payload["usage"]
        except ValueError as exc:
            raise _invalid() from exc
        text = state._snapshot(message)
        state.finished = True
        if text:
            yield text
        return
    async for event, data in sse_frames(response.aiter_lines()):
        text = state.feed(event, data)
        if text:
            yield text
        if state.terminal:
            break
    state.result()


async def post_streamed_chat(
    client: httpx.AsyncClient, url: str, body: dict[str, Any]
) -> httpx.Response:
    """Buffer a streamed structured/tool response without changing the HTTP caller contract."""
    async with client.stream(
        "POST",
        url,
        json={**body, "stream": True},
        headers={"Accept": "text/event-stream, application/json"},
    ) as response:
        if response.status_code != 200:
            await response.aread()
            return response
        state = ChatStream()
        async for _ in stream_chat(response, state):
            pass
        return httpx.Response(200, json=state.result(), request=response.request)
