from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

import httpx

from app.config import Settings, normalize_api_key
from app.services.ninerouter import NineRouterClient, retry_json_chat
from app.services.provider_errors import ProviderError, classify_http


class AiServiceDecisionClient:
    """Durable typed-decision client for the AISERVICE gateway."""

    def __init__(self, settings: Settings, *, request_namespace: str) -> None:
        self._settings = settings
        self._direct = settings.active_ai_provider == "ninerouter_direct"
        self._ninerouter = NineRouterClient(settings) if self._direct else None
        self._path = settings.aiservice_decision_path
        self._base = (settings.voicesanj_base_url or "").rstrip("/")
        key = normalize_api_key(settings.decision_api_key or settings.voicesanj_api_key)
        if not self._base or not key:
            raise ProviderError("decision_provider_config", "تنظیمات سرویس تصمیم‌گیری کامل نیست.")
        self._threshold = settings.decision_confidence_threshold
        self._ninerouter_prompt = (
            settings.ninerouter_direct_prompt
            if self._direct
            else settings.ninerouter_decision_prompt
        )
        self._namespace = request_namespace
        self._timeout = min(max(settings.llm_timeout_seconds, 30.0), 300.0)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=15.0),
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        )

    async def decide(self, *, model: str, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        if self._ninerouter_prompt:
            questions = {
                key: {
                    **question,
                    "instructions": (
                        f"{str(question.get('instructions') or '').rstrip()}\n\n"
                        f"{self._ninerouter_prompt}"
                    ),
                }
                for key, question in questions.items()
            }
        if self._direct:
            assert self._ninerouter is not None
            contract = {
                "version": "v1",
                "answers": {
                    key: {
                        "type": question.get("type"),
                        "answer": "typed answer or null when abstained",
                        "probabilities": {"candidate": 0.0},
                        "confidence": "number from 0 to 1",
                        "margin": "number from 0 to 1",
                        "abstained": False,
                        "evidence": ["short verbatim excerpts from the supplied state"],
                    }
                    for key, question in questions.items()
                },
            }
            parsed = await retry_json_chat(
                self._ninerouter,
                model=model,
                max_tokens=self._settings.llm_max_tokens,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Answer the typed decision questions from the supplied state. "
                            "Return only JSON matching this contract and never invent evidence.\n"
                            + json.dumps(contract, ensure_ascii=False)
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"state": state, "questions": questions},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    },
                ],
            )
            return _validate_direct_decision(parsed, questions)
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
        if self._ninerouter is not None:
            await self._ninerouter.close()
        await self._client.aclose()


def _validate_direct_decision(
    payload: dict[str, Any], questions: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    answers = payload.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ProviderError(
            "decision_provider_response", "خروجی تصمیم‌گیری 9Router با پرسش‌ها منطبق نیست."
        )
    normalized: dict[str, Any] = {}
    for key, question in questions.items():
        answer = answers.get(key)
        if not isinstance(answer, dict):
            raise ProviderError("decision_provider_response", "پاسخ تصمیم‌گیری نامعتبر است.")
        confidence = answer.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise ProviderError("decision_provider_response", "اطمینان تصمیم‌گیری نامعتبر است.")
        question_type = str(question.get("type") or "")
        if answer.get("type") != question_type:
            raise ProviderError("decision_provider_response", "نوع پاسخ تصمیم‌گیری نامعتبر است.")
        margin = answer.get("margin")
        if not isinstance(margin, (int, float)) or not 0 <= float(margin) <= 1:
            raise ProviderError("decision_provider_response", "حاشیه اطمینان تصمیم‌گیری نامعتبر است.")
        abstained = answer.get("abstained")
        if not isinstance(abstained, bool):
            raise ProviderError("decision_provider_response", "وضعیت abstain تصمیم‌گیری نامعتبر است.")
        value = answer.get("answer")
        criteria = question.get("criteria")
        if not abstained and question_type == "score":
            if not isinstance(value, (int, float)) or not isinstance(criteria, list) or not 0 <= float(value) < len(criteria):
                raise ProviderError("decision_provider_response", "امتیاز تصمیم‌گیری خارج از محدوده است.")
        if not abstained and question_type == "choice" and isinstance(criteria, dict) and value not in criteria:
            raise ProviderError("decision_provider_response", "انتخاب تصمیم‌گیری خارج از گزینه‌های مجاز است.")
        probabilities = answer.get("probabilities")
        if not isinstance(probabilities, dict) or any(
            not isinstance(item, (int, float)) or not 0 <= float(item) <= 1
            for item in probabilities.values()
        ):
            raise ProviderError("decision_provider_response", "احتمال‌های تصمیم‌گیری نامعتبر است.")
        evidence = answer.get("evidence")
        if not isinstance(evidence, list) or any(
            not isinstance(item, str) or not item.strip() for item in evidence
        ):
            raise ProviderError("decision_provider_response", "شواهد تصمیم‌گیری نامعتبر است.")
        normalized[key] = {
            "type": question_type,
            "answer": value,
            "probabilities": {str(name): float(item) for name, item in probabilities.items()},
            "confidence": float(confidence),
            "margin": float(margin),
            "abstained": abstained,
            "evidence": [item.strip() for item in evidence],
        }
    return {
        "version": "v1",
        "model": str(payload.get("model") or "ninerouter-direct"),
        "engine": "ninerouter_chat_adapter",
        "answers": normalized,
        "capabilities": ["typed_json_adapter"],
        "latency_ms": 0.0,
    }
