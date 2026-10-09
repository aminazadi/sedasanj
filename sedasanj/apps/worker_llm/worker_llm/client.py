from __future__ import annotations

import abc
import asyncio
import hashlib
import itertools
import json
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.config import Settings, normalize_api_key
from app.metrics import llm_tokens_per_second
from app.services.ninerouter import response_json
from app.services.provider_chat import ChatStream, chat_message, post_streamed_chat, stream_chat
from app.services.provider_errors import ProviderError, classify_http, inspect_payload
from app.services.voicesanj import VOICESANJ_USER_AGENT

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


def available_prompt_versions() -> frozenset[str]:
    return frozenset(path.stem for path in PROMPT_DIR.glob("*.txt"))


def load_prompt(version: str) -> str:
    return (PROMPT_DIR / f"{version}.txt").read_text(encoding="utf-8").strip()


def load_run_prompt(version: str, system_prompt: str | None) -> str:
    if system_prompt and system_prompt.strip():
        return system_prompt.strip()
    return load_prompt(version)


def _object_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if start is None:
            if char == "{":
                start = index
                depth = 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidates.append(text[start : index + 1])
                start = None
    if start is not None:
        candidates.append(text[start:])
    return candidates


def _previous_non_whitespace(text: str, position: int) -> int | None:
    for index in range(position - 1, -1, -1):
        if not text[index].isspace():
            return index
    return None


def _repair_at_decode_error(text: str, exc: json.JSONDecodeError) -> str | None:
    position = exc.pos
    current = text[position] if position < len(text) else ""
    previous = _previous_non_whitespace(text, position)

    if exc.msg == "Expecting ',' delimiter":
        if current and (current in {'"', "{", "[", "-"} or current.isdigit()):
            return f"{text[:position]},{text[position:]}"
        if current in {"t", "f", "n"}:
            return f"{text[:position]},{text[position:]}"
        if previous is not None and text[previous] == '"' and (
            previous == 0 or text[previous - 1] != "\\"
        ):
            return f'{text[:previous]}\\"{text[previous + 1:]}'

    if (
        exc.msg == "Expecting property name enclosed in double quotes"
        and current == "}"
        and previous is not None
        and text[previous] == ","
    ):
        return f"{text[:previous]}{text[previous + 1:]}"

    if (
        exc.msg == "Expecting value"
        and current == "]"
        and previous is not None
        and text[previous] == ","
    ):
        return f"{text[:previous]}{text[previous + 1:]}"

    if exc.msg == "Invalid control character at" and position < len(text):
        replacements = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
        replacement = replacements.get(text[position])
        if replacement is not None:
            return f"{text[:position]}{replacement}{text[position + 1:]}"
    return None


def _load_json_object(candidate: str) -> dict[str, Any]:
    repaired = candidate
    last_error: json.JSONDecodeError | None = None
    for _ in range(20):
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError as exc:
            last_error = exc
            next_value = _repair_at_decode_error(repaired, exc)
            if next_value is None or next_value == repaired:
                break
            repaired = next_value
            continue
        if not isinstance(parsed, dict):
            raise ValueError("model output is not a JSON object")
        return parsed
    if last_error is not None:
        raise last_error
    raise ValueError("model output is not a JSON object")


def extract_json(raw: str) -> dict[str, Any]:
    """Extract an object and recover conservative, common model JSON mistakes."""
    candidates = _object_candidates(raw.strip())
    if not candidates:
        raise ValueError("no JSON object in model output")
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return _load_json_object(candidate)
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


class LlmClient(abc.ABC):
    @abc.abstractmethod
    async def complete(
        self, system: str, user: str, *, json_object: bool = True, model: str | None = None
    ) -> str: ...

    async def close(self) -> None:
        return None

    async def complete_with_tools(
        self,
        system: str,
        user: str,
        tools: list[dict[str, Any]],
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        raise ProviderError(
            "llm_tools_unsupported",
            "مدل انتخاب‌شده فراخوانی Native ابزار را پشتیبانی نمی‌کند.",
            retryable=False,
        )

    async def stream(
        self, system: str, user: str, *, json_object: bool = True, model: str | None = None
    ) -> AsyncIterator[str]:
        answer = await self.complete(system, user, json_object=json_object, model=model)
        for word in re.findall(r"\S+\s*", answer):
            yield word


class LlamaClient(LlmClient):
    """Round-robin over `LLAMA_SERVER_URLS` (§9.2)."""

    def __init__(self, settings: Settings) -> None:
        self._urls = settings.llama_urls
        if not self._urls:
            raise RuntimeError("LLAMA_SERVER_URLS is empty")
        self._cycle = itertools.cycle(self._urls)
        self._model = settings.llm_model
        self._max_tokens = settings.llm_max_tokens
        self._direct = settings.active_ai_provider == "ninerouter_direct"
        self._extra_prompt = settings.ninerouter_direct_prompt.strip()
        headers: dict[str, str] = {}
        api_key = normalize_api_key(settings.openai_api_key)
        self._secret = api_key
        if self._direct and not api_key:
            raise ProviderError(
                "ninerouter_configuration",
                "کلید اتصال مستقیم 9Router تنظیم نشده است.",
                retryable=False,
            )
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        timeout: float | httpx.Timeout = settings.llm_timeout_seconds
        if settings.active_ai_provider == "ninerouter_direct":
            timeout = httpx.Timeout(
                connect=settings.ninerouter_connect_timeout_seconds,
                read=settings.ninerouter_read_timeout_seconds,
                write=max(settings.ninerouter_read_timeout_seconds, 120.0),
                pool=settings.ninerouter_connect_timeout_seconds,
            )
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)

    async def _post_chat(self, url: str, body: dict[str, Any]) -> httpx.Response:
        if self._direct:
            return await post_streamed_chat(self._client, url, body)
        return await self._client.post(url, json=body)

    async def complete(
        self, system: str, user: str, *, json_object: bool = True, model: str | None = None
    ) -> str:
        if self._extra_prompt:
            system = f"{system.rstrip()}\n\n{self._extra_prompt}"
        body: dict[str, Any] = {
            "model": model or self._model,
            "temperature": 0.2,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_object:
            body["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        for _ in range(3 if self._direct else len(self._urls)):
            base = next(self._cycle)
            started = time.perf_counter()
            try:
                response = await self._post_chat(f"{base}/v1/chat/completions", body)
                if response.status_code == 400 and json_object and "response_format" in body:
                    retry_body = {
                        key: value for key, value in body.items() if key != "response_format"
                    }
                    response = await self._post_chat(f"{base}/v1/chat/completions", retry_body)
                classified = classify_http(
                    response.status_code,
                    response.text.replace(self._secret, "[redacted]")
                    if self._secret
                    else response.text,
                    kind="llm",
                )
                if classified is not None:
                    raise classified
                data = response_json(response)
                message = chat_message(data)
            except ProviderError as exc:
                if not exc.retryable:
                    raise
                last_error = exc
            except httpx.HTTPError as exc:
                if isinstance(exc, httpx.TimeoutException):
                    last_error = ProviderError(
                        "llm_provider_timeout",
                        "پاسخ سرویس هوش مصنوعی در زمان مقرر آماده نشد. "
                        "درخواست به‌صورت کنترل‌شده دوباره تلاش می‌شود.",
                        retryable=True,
                    )
                else:
                    last_error = ProviderError(
                        "llm_provider_unavailable",
                        "ارتباط با سرویس هوش مصنوعی موقتاً برقرار نشد. "
                        "درخواست به‌صورت کنترل‌شده دوباره تلاش می‌شود.",
                        retryable=True,
                    )
            else:
                elapsed = max(time.perf_counter() - started, 1e-6)
                completion_tokens = int(
                    (data.get("usage") or {}).get("completion_tokens")
                    or (data.get("usage") or {}).get("output_tokens")
                    or 0
                )
                if completion_tokens:
                    llm_tokens_per_second.observe(completion_tokens / elapsed)
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise ProviderError("llm_provider_response", "مدل متن معتبری برنگرداند.")
                return content

        if last_error is not None:
            raise last_error
        raise RuntimeError("all llama-server endpoints failed without an error")

    async def stream(
        self, system: str, user: str, *, json_object: bool = True, model: str | None = None
    ) -> AsyncIterator[str]:
        if self._extra_prompt:
            system = f"{system.rstrip()}\n\n{self._extra_prompt}"
        body: dict[str, Any] = {
            "model": model or self._model,
            "temperature": 0.2,
            "max_tokens": self._max_tokens,
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_object:
            body["response_format"] = {"type": "json_object"}

        emitted = False
        last_error: Exception | None = None
        for _ in range(3 if self._direct else len(self._urls)):
            base = next(self._cycle)
            try:
                async with self._client.stream(
                    "POST", f"{base}/v1/chat/completions", json=body
                ) as response:
                    if response.status_code == 400 and json_object:
                        retry_body = {
                            key: value for key, value in body.items() if key != "response_format"
                        }
                        async with self._client.stream(
                            "POST", f"{base}/v1/chat/completions", json=retry_body
                        ) as retry_response:
                            async for chunk in self._stream_response(retry_response):
                                emitted = True
                                yield chunk
                        return
                    async for chunk in self._stream_response(response):
                        emitted = True
                        yield chunk
                    return
            except ProviderError as exc:
                if emitted or not exc.retryable:
                    raise
                last_error = exc
            except httpx.HTTPError as exc:
                if emitted:
                    raise ProviderError(
                        "llm_provider_stream_interrupted",
                        "جریان پاسخ مدل قطع شد؛ دوباره تلاش کنید.",
                    ) from exc
                last_error = ProviderError(
                    "llm_provider_unavailable",
                    "ارتباط با سرویس هوش مصنوعی موقتاً برقرار نشد.",
                    retryable=isinstance(exc, httpx.TimeoutException),
                )
        if last_error is not None:
            raise last_error
        raise RuntimeError("all llama-server endpoints failed without an error")

    async def complete_with_tools(
        self,
        system: str,
        user: str,
        tools: list[dict[str, Any]],
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        if self._extra_prompt:
            system = f"{system.rstrip()}\n\n{self._extra_prompt}"
        body = {
            "model": model or self._model,
            "temperature": 0.2,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "tools": tools,
            "tool_choice": "auto",
        }
        last_error: Exception | None = None
        for attempt in range(3 if self._direct else len(self._urls)):
            base = next(self._cycle)
            try:
                response = await self._post_chat(f"{base}/v1/chat/completions", body)
                classified = classify_http(
                    response.status_code,
                    response.text.replace(self._secret, "[redacted]")
                    if self._secret
                    else response.text,
                    kind="llm",
                )
                if classified is not None:
                    raise classified
                payload = response_json(response)
                message = chat_message(payload)
                if not isinstance(message, dict):
                    raise ProviderError(
                        "llm_provider_response", "سرویس هوش مصنوعی پاسخ نامعتبر داد."
                    )
                return message
            except ProviderError as exc:
                if not exc.retryable:
                    raise
                last_error = exc
            except httpx.HTTPError as exc:
                last_error = exc
            if attempt < 2 and self._direct:
                await asyncio.sleep(0.25 * (2**attempt))
        if isinstance(last_error, ProviderError):
            raise last_error
        raise ProviderError(
            "llm_provider_unavailable",
            "ارتباط با سرویس هوش مصنوعی موقتاً برقرار نشد.",
            retryable=True,
        ) from last_error

    @staticmethod
    async def _stream_response(response: httpx.Response) -> AsyncIterator[str]:
        if response.status_code != 200:
            if (
                classified := classify_http(
                    response.status_code, (await response.aread()).decode(), kind="llm"
                )
            ) is not None:
                raise classified
            raise ProviderError("llm_provider_response", "سرویس هوش مصنوعی پاسخ نامنتظره داد.")
        state = ChatStream()
        async for text in stream_chat(response, state):
            yield text
        if not state.text.strip():
            raise ProviderError(
                "llm_provider_response", "مدل پاسخ متنی برنگرداند.", retryable=False
            )

    async def close(self) -> None:
        await self._client.aclose()


class VoiceSanjChatClient(LlmClient):
    """Submit durable chat work, poll its state, and fetch the finished result."""

    def __init__(
        self,
        settings: Settings,
        *,
        request_namespace: str | None = None,
        purpose: str = "analysis",
    ) -> None:
        self._base = (settings.voicesanj_base_url or "").rstrip("/")
        if not self._base:
            raise RuntimeError("VOICESANJ_BASE_URL is empty")
        api_key = normalize_api_key(settings.voicesanj_api_key)
        if not api_key:
            raise RuntimeError("VoiceSanj API key is required; save it in admin model settings")
        self._model = settings.voicesanj_llm_model
        self._path = (
            settings.aiservice_chat_path if purpose == "chat" else settings.aiservice_analysis_path
        )
        self._ninerouter_prompt = (
            settings.ninerouter_chat_prompt
            if purpose == "chat"
            else settings.ninerouter_analysis_prompt
        )
        self._max_tokens = settings.llm_max_tokens
        self._poll_interval = max(settings.voicesanj_poll_interval_seconds, 0.1)
        self._poll_timeout = min(
            settings.voicesanj_poll_timeout_seconds,
            max(settings.analysis_timeout_seconds - 30.0, 30.0),
        )
        # A stable AnalysisRun ID makes a resubmission after an HTTP timeout
        # resolve to the same provider task, without sharing work across calls.
        self._request_namespace = request_namespace or str(uuid4())
        timeout = httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=15.0)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": VOICESANJ_USER_AGENT,
                "Accept": "application/json",
            },
            http2=False,
        )

    async def complete(
        self, system: str, user: str, *, json_object: bool = True, model: str | None = None
    ) -> str:
        if self._path != "/v1/chat/tasks":
            return await self._complete_synchronous(
                system, user, json_object=json_object, model=model
            )
        del json_object  # AsyncChatRequest does not expose response_format.
        body = self._request_body(system, user, model=model)
        started = time.perf_counter()
        identity = json.dumps(body, ensure_ascii=False, sort_keys=True)
        key = (
            "cbi-chat-"
            + hashlib.sha256(f"{self._request_namespace}:{identity}".encode()).hexdigest()
        )
        task_id = await self.submit_task(body, idempotency_key=key)
        deadline = time.monotonic() + self._poll_timeout
        while True:
            if time.monotonic() >= deadline:
                raise ProviderError(
                    "llm_provider_timeout",
                    "نتیجه تحلیل در مهلت این تلاش آماده نشد؛ "
                    "همان درخواست در تلاش بعدی پیگیری می‌شود.",
                    retryable=True,
                )
            status = await self.task_status(task_id)
            state = status.get("status")
            if state == "succeeded":
                content, tokens = await self.task_result(task_id)
                if tokens:
                    llm_tokens_per_second.observe(
                        tokens / max(time.perf_counter() - started, 1e-6)
                    )
                return content
            if state in {"failed", "cancelled", "partially_succeeded"}:
                raise ProviderError(
                    "llm_provider_task_failed",
                    "سرویس تحلیل را ناموفق اعلام کرد "
                    f"({str(status.get('error_code') or state)[:80]}).",
                    retryable=False,
                )
            if state not in {"queued", "running", "retrying"}:
                raise ProviderError("llm_provider_response", "وضعیت ناشناخته از سرویس دریافت شد.")
            await asyncio.sleep(min(self._poll_interval, max(deadline - time.monotonic(), 0)))

    async def _complete_synchronous(
        self, system: str, user: str, *, json_object: bool, model: str | None
    ) -> str:
        body = self._request_body(system, user, model=model)
        if json_object and self._path.startswith("/v1/ninerouter/"):
            body["response_format"] = {"type": "json_object"}
        try:
            response = await self._client.post(f"{self._base}{self._path}", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "llm_provider_timeout",
                "پاسخ سرویس هوش مصنوعی در زمان مقرر آماده نشد.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                "llm_provider_unavailable",
                "ارتباط با سرویس هوش مصنوعی برقرار نشد.",
                retryable=True,
            ) from exc
        self._check_response(response, expected=200)
        payload = response.json()
        inspect_payload(payload, kind="llm")
        choices = payload.get("choices") if isinstance(payload, dict) else None
        message = choices[0].get("message") if isinstance(choices, list) and choices else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("llm_provider_empty", "سرویس هوش مصنوعی پاسخ متنی برنگرداند.")
        return content

    async def complete_with_tools(
        self,
        system: str,
        user: str,
        tools: list[dict[str, Any]],
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        body = self._request_body(system, user, model=model)
        body["tools"] = tools
        body["tool_choice"] = "auto"
        if self._path == "/v1/chat/tasks":
            identity = json.dumps(body, ensure_ascii=False, sort_keys=True)
            key = "cbi-tools-" + hashlib.sha256(
                f"{self._request_namespace}:{identity}".encode()
            ).hexdigest()
            task_id = await self.submit_task(body, idempotency_key=key)
            deadline = time.monotonic() + self._poll_timeout
            while time.monotonic() < deadline:
                status = await self.task_status(task_id)
                if status.get("status") == "succeeded":
                    payload = await self.task_result_payload(task_id)
                    choices = payload.get("choices")
                    message = choices[0].get("message") if isinstance(choices, list) and choices else None
                    if isinstance(message, dict):
                        return message
                    break
                if status.get("status") in {"failed", "cancelled", "partially_succeeded"}:
                    break
                await asyncio.sleep(self._poll_interval)
            raise ProviderError("llm_provider_response", "فراخوانی ابزار توسط مدل کامل نشد.")
        response = await self._client.post(f"{self._base}{self._path}", json=body)
        self._check_response(response, expected=200)
        payload = response.json()
        choices = payload.get("choices") if isinstance(payload, dict) else None
        message = choices[0].get("message") if isinstance(choices, list) and choices else None
        if not isinstance(message, dict):
            raise ProviderError("llm_provider_response", "سرویس هوش مصنوعی پاسخ نامعتبر داد.")
        return message

    def _request_body(
        self, system: str, user: str, *, model: str | None = None
    ) -> dict[str, Any]:
        if self._ninerouter_prompt:
            system = f"{system.rstrip()}\n\n{self._ninerouter_prompt}"
        return {
            "model": model or self._model,
            "temperature": 0.2,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    async def submit(
        self, system: str, user: str, *, model: str | None = None, idempotency_key: str
    ) -> str:
        return await self.submit_task(
            self._request_body(system, user, model=model),
            idempotency_key=idempotency_key,
        )

    async def submit_task(self, body: dict[str, Any], *, idempotency_key: str) -> str:
        try:
            response = await self._client.post(
                f"{self._base}/v1/chat/tasks",
                headers={"Idempotency-Key": idempotency_key},
                json=body,
            )
            self._check_response(response, expected=202)
            task = response.json()
            task_id = task.get("task_id") if isinstance(task, dict) else None
            if not isinstance(task_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", task_id):
                raise ProviderError(
                    "llm_provider_response", "شناسه کار سرویس هوش مصنوعی نامعتبر است."
                )
            return task_id
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "llm_provider_timeout",
                "درخواست سرویس هوش مصنوعی در زمان مقرر پاسخ نداد؛ "
                "تلاش بعدی با همان شناسه انجام می‌شود.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                "llm_provider_unavailable",
                "ارتباط با سرویس هوش مصنوعی موقتاً قطع شد. "
                "درخواست به‌صورت کنترل‌شده دوباره زمان‌بندی می‌شود.",
                retryable=True,
            ) from exc

    async def task_status(self, task_id: str) -> dict[str, Any]:
        path = f"{self._base}/v1/tasks/{task_id}"
        try:
            response = await self._client.get(path)
            self._check_response(response, expected=200)
            payload = response.json()
            if not isinstance(payload, dict):
                raise ProviderError("llm_provider_response", "وضعیت کار سرویس نامعتبر است.")
            inspect_payload(payload, kind="llm")
            return payload
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError(
                "llm_provider_unavailable",
                "ارتباط با سرویس هوش مصنوعی موقتاً قطع شد.",
                retryable=True,
            ) from exc

    async def task_result(self, task_id: str) -> tuple[str, int]:
        result = await self.task_result_payload(task_id)
        choices = result.get("choices")
        message = (
            choices[0].get("message")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict)
            else None
        )
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("llm_provider_empty", "سرویس هوش مصنوعی پاسخ متنی برنگرداند.")
        usage = result.get("usage")
        tokens = int(usage.get("completion_tokens") or 0) if isinstance(usage, dict) else 0
        return content, tokens

    async def task_result_payload(self, task_id: str) -> dict[str, Any]:
        path = f"{self._base}/v1/tasks/{task_id}/result"
        response = await self._client.get(path)
        if response.status_code == 409:
            raise ProviderError(
                "llm_result_pending", "نتیجه هنوز آماده دریافت نیست.", retryable=True
            )
        self._check_response(response, expected=200)
        result = response.json()
        inspect_payload(result, kind="llm")
        if not isinstance(result, dict):
            raise ProviderError("llm_provider_response", "نتیجه سرویس نامعتبر است.")
        return result

    @staticmethod
    def _check_response(response: httpx.Response, *, expected: int) -> None:
        if response.status_code == expected:
            return
        classified = classify_http(response.status_code, response.text, kind="llm")
        if classified is not None:
            raise classified
        raise ProviderError("llm_provider_response", "سرویس هوش مصنوعی پاسخ نامنتظره داد.")

    async def close(self) -> None:
        await self._client.aclose()


class FixtureClient(LlmClient):
    """Offline stand-in until the Dorna GGUF is provisioned (§17.2)."""

    async def complete(
        self, system: str, user: str, *, json_object: bool = True, model: str | None = None
    ) -> str:
        head = " ".join(user.split()[:12])
        payload = {
            "summary": f"خلاصه آزمایشی مکالمه: {head}",
            "keywords": ["پشتیبانی", "تماس"],
            "sentiment": {
                "overall": "neutral",
                "score": 0.5,
                "phrases": [],
                "caller": {
                    "start": {"label": "neutral", "score": 0.5},
                    "end": {"label": "satisfied", "score": 0.6},
                    "overall": {"label": "neutral", "score": 0.5},
                },
                "agent": {
                    "start": {"label": "neutral", "score": 0.5},
                    "end": {"label": "satisfied", "score": 0.6},
                    "overall": {"label": "satisfied", "score": 0.55},
                },
            },
            "intent": "other",
            "ner": {
                "persons": [],
                "dates": [],
                "amounts": [],
                "phone_numbers": [],
                "organizations": [],
            },
            "action_items": [],
            "topics": ["پشتیبانی"],
        }
        return json.dumps(payload, ensure_ascii=False)


def build_client(
    settings: Settings,
    *,
    request_namespace: str | None = None,
    purpose: str = "analysis",
) -> LlmClient:
    if settings.llm_client == "fixture":
        return FixtureClient()
    if settings.llm_client == "voicesanj":
        return VoiceSanjChatClient(
            settings, request_namespace=request_namespace, purpose=purpose
        )
    return LlamaClient(settings)
