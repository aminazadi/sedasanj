from __future__ import annotations

import asyncio
import json
import math
import re
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, normalize_api_key
from app.services.provider_chat import chat_message, post_streamed_chat
from app.services.provider_errors import ProviderError, classify_http, inspect_payload

SECRET_PATTERN = re.compile(r"(?i)(bearer\s+|9r_|sk-)[A-Za-z0-9._-]+")
MODEL_PATHS = {
    "chat": "/v1/models",
    "stt": "/v1/models/stt",
    "embedding": "/v1/models/embedding",
}
MINIMUM_SAFE_VERSION = (0, 5, 2)


def redact_detail(value: object) -> str:
    return SECRET_PATTERN.sub(lambda match: f"{match.group(1)}[redacted]", str(value))[:500]


def response_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError("provider_response", "پاسخ سرویس JSON معتبر نیست.") from exc


class NineRouterClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.ninerouter_base_url.rstrip("/")
        key = normalize_api_key(settings.ninerouter_api_key)
        self._secret = key
        if not self._base or not key:
            raise ProviderError(
                "ninerouter_configuration",
                "آدرس یا کلید اتصال مستقیم 9Router تنظیم نشده است.",
                retryable=False,
            )
        self._headers = {
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "sedasanj/ninerouter-direct",
        }
        self._timeout = httpx.Timeout(
            connect=settings.ninerouter_connect_timeout_seconds,
            read=settings.ninerouter_read_timeout_seconds,
            write=max(settings.ninerouter_read_timeout_seconds, 120.0),
            pool=settings.ninerouter_connect_timeout_seconds,
        )
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=self._timeout,
            follow_redirects=False,
            http2=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        expected: set[int] | None = None,
        kind: str = "llm",
        **kwargs: Any,
    ) -> httpx.Response:
        expected = expected or {200}
        last_error: ProviderError | None = None
        for attempt in range(3):
            try:
                if method == "POST" and path == "/v1/chat/completions":
                    response = await post_streamed_chat(
                        self._client, f"{self._base}{path}", kwargs["json"]
                    )
                else:
                    response = await self._client.request(method, f"{self._base}{path}", **kwargs)
            except httpx.TimeoutException as exc:
                last_error = ProviderError(
                    f"{kind}_provider_timeout",
                    "ارتباط مستقیم با 9Router timeout شد.",
                    retryable=True,
                )
                if attempt == 2:
                    raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = ProviderError(
                    f"{kind}_provider_unavailable",
                    "ارتباط مستقیم با 9Router برقرار نشد.",
                    retryable=True,
                )
                if attempt == 2:
                    raise last_error from exc
            else:
                if response.status_code in expected:
                    return response
                safe_detail = response.text.replace(self._secret, "[redacted]")
                classified = classify_http(response.status_code, safe_detail, kind=kind)
                last_error = classified or ProviderError(
                    f"{kind}_provider_response",
                    f"9Router پاسخ HTTP {response.status_code} داد: {redact_detail(safe_detail)}",
                    retryable=response.status_code == 429 or response.status_code >= 500,
                )
                if not last_error.retryable or attempt == 2:
                    raise last_error
            await asyncio.sleep(0.25 * (2**attempt))
        if last_error is not None:
            raise last_error
        raise ProviderError(f"{kind}_provider_response", "9Router پاسخ معتبری برنگرداند.")

    async def health(self) -> dict[str, Any]:
        response = await self._request("GET", "/api/health")
        payload = response_json(response)
        if not isinstance(payload, dict):
            raise ProviderError("ninerouter_response", "پاسخ سلامت 9Router نامعتبر است.")
        version = str(payload.get("version") or "").strip().lstrip("v")
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
        if match and tuple(int(part) for part in match.groups()) < MINIMUM_SAFE_VERSION:
            raise ProviderError(
                "ninerouter_unsafe_version",
                "نسخه 9Router باید حداقل 0.5.2 باشد.",
                retryable=False,
            )
        return payload

    async def list_models(self, kind: str) -> list[dict[str, Any]]:
        if kind not in MODEL_PATHS:
            raise ValueError("kind must be chat, stt, or embedding")
        response = await self._request("GET", MODEL_PATHS[kind])
        payload = response_json(response)
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ProviderError("ninerouter_response", "فهرست مدل‌های 9Router نامعتبر است.")
        return [row for row in rows if isinstance(row, dict) and str(row.get("id") or "").strip()]

    async def embedding(self, *, model: str, content: str) -> list[float]:
        response = await self._request(
            "POST",
            "/v1/embeddings",
            kind="llm",
            json={"model": model, "input": content, "encoding_format": "float"},
        )
        payload = response_json(response)
        inspect_payload(payload, kind="llm")
        data = payload.get("data") if isinstance(payload, dict) else None
        vector = (
            data[0].get("embedding")
            if isinstance(data, list) and data and isinstance(data[0], dict)
            else None
        )
        if (
            not isinstance(vector, list)
            or not vector
            or len(vector) > 4096
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in vector
            )
        ):
            raise ProviderError("embedding_provider_response", "9Router بردار معتبری برنگرداند.")
        return [float(value) for value in vector]

    async def chat(self, body: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("POST", "/v1/chat/completions", kind="llm", json=body)
        payload = response_json(response)
        chat_message(payload)
        return payload

    async def transcribe(
        self,
        path: Path,
        *,
        model: str,
        language: str = "fa",
        prompt: str | None = None,
    ) -> dict[str, Any]:
        normalized = model.lower().rsplit("/", 1)[-1]
        response_format = (
            "json"
            if normalized.startswith("gpt-4o-") and "transcribe" in normalized
            else "verbose_json"
        )
        audio = path.read_bytes()

        async def request(format_name: str) -> httpx.Response:
            form = {"model": model, "language": language, "response_format": format_name}
            if prompt:
                form["prompt"] = prompt
            return await self._request(
                "POST",
                "/v1/audio/transcriptions",
                kind="asr",
                files={"file": (path.name, audio, "audio/wav")},
                data=form,
            )

        response = await request(response_format)
        try:
            payload: Any = response.json()
        except ValueError:
            payload = {"text": response.text.strip()}
        inspect_payload(payload, kind="asr")
        text = _transcription_text(payload)
        if not text and response_format != "text":
            fallback = await request("text")
            try:
                fallback_payload: Any = fallback.json()
            except ValueError:
                fallback_payload = fallback.text
            inspect_payload(fallback_payload, kind="asr")
            text = _transcription_text(fallback_payload)
            if text:
                payload = {"text": text}
        if not text:
            raise ProviderError(
                "asr_provider_empty", "9Router متن قابل استفاده‌ای برنگرداند.", retryable=False
            )
        if not isinstance(payload, dict):
            payload = {"text": text}
        payload["text"] = text
        payload.setdefault("model", model)
        return payload


def _transcription_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return ""
    for key in ("text", "transcript", "transcription"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("data", "result", "output"):
        nested = _transcription_text(payload.get(key))
        if nested:
            return nested
    return ""


async def retry_json_chat(
    client: NineRouterClient,
    *,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    last_error: Exception | None = None
    for attempt in range(2):
        payload = await client.chat(body)
        content = payload["choices"][0].get("message", {}).get("content")
        try:
            parsed = json.loads(str(content))
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, ValueError) as exc:
            last_error = exc
        if attempt == 0:
            body["messages"] = [
                *messages,
                {"role": "assistant", "content": str(content or "")},
                {
                    "role": "user",
                    "content": (
                        "خروجی قبلی JSON معتبر نبود. فقط یک شیء JSON معتبر مطابق قرارداد برگردان."
                    ),
                },
            ]
            await asyncio.sleep(0)
    raise ProviderError(
        "llm_provider_response", "9Router پس از یک تلاش اصلاح، JSON معتبر برنگرداند."
    ) from last_error
