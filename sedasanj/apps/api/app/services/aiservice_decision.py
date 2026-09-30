from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

import httpx

from app.config import Settings, normalize_api_key
from app.services.provider_errors import ProviderError, classify_http


class AiServiceDecisionClient:
    """Durable typed-decision client for the AISERVICE gateway."""

    def __init__(self, settings: Settings, *, request_namespace: str) -> None:
        self._path = settings.aiservice_decision_path
        self._base = (settings.voicesanj_base_url or "").rstrip("/")
        key = normalize_api_key(settings.decision_api_key or settings.voicesanj_api_key)
        if not self._base or not key:
            raise ProviderError("decision_provider_config", "تنظیمات سرویس تصمیم‌گیری کامل نیست.")
        self._threshold = settings.decision_confidence_threshold
        self._namespace = request_namespace
        self._timeout = min(max(settings.llm_timeout_seconds, 30.0), 300.0)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=15.0),
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        )

    async def decide(self, *, model: str, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        body = {"model": model, "state": state, "questions": questions, "confidence_threshold": self._threshold}
        fingerprint = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        idempotency_key = "cbi-decision-" + hashlib.sha256(f"{self._namespace}:{fingerprint}".encode()).hexdigest()
        response = await self._request("POST", self._path, json=body, headers={"Idempotency-Key": idempotency_key}, expected={200, 202})
        task = response.json()
        if not isinstance(task, dict) or not isinstance(task.get("task_id"), str):
            raise ProviderError("decision_provider_response", "پاسخ task سرویس تصمیم‌گیری نامعتبر است.")
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            status = await self._request("GET", f"/v1/tasks/{task['task_id']}", expected={200})
            payload = status.json()
            if not isinstance(payload, dict):
                raise ProviderError("decision_provider_response", "وضعیت task تصمیم‌گیری نامعتبر است.")
            if payload.get("status") == "succeeded":
                result = await self._request("GET", f"/v1/tasks/{task['task_id']}/result", expected={200})
                parsed = result.json()
                if not isinstance(parsed, dict) or parsed.get("version") != "v1" or not isinstance(parsed.get("answers"), dict):
                    raise ProviderError("decision_provider_response", "خروجی typed سرویس تصمیم‌گیری نامعتبر است.")
                return parsed
            if payload.get("status") in {"failed", "cancelled"}:
                raise ProviderError("decision_provider_task_failed", "سرویس تصمیم‌گیری task را ناموفق اعلام کرد.", retryable=False)
            await asyncio.sleep(0.5)
        raise ProviderError("decision_provider_timeout", "مهلت دریافت نتیجه تصمیم‌گیری تمام شد.", retryable=True)

    async def _request(self, method: str, path: str, *, expected: set[int], **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, f"{self._base}{path}", **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderError("decision_provider_timeout", "ارتباط با سرویس تصمیم‌گیری timeout شد.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("decision_provider_unavailable", "ارتباط با سرویس تصمیم‌گیری برقرار نشد.", retryable=True) from exc
        if response.status_code not in expected:
            classified = classify_http(response.status_code, response.text, kind="llm")
            if classified is not None:
                raise ProviderError(f"decision_{classified.code}", classified.detail, retryable=classified.retryable)
            raise ProviderError("decision_provider_response", "سرویس تصمیم‌گیری پاسخ نامنتظره داد.")
        return response

    async def close(self) -> None:
        await self._client.aclose()
