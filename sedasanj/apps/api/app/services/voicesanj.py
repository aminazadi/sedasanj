from __future__ import annotations

import asyncio
import gzip
import logging
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.config import Settings, normalize_api_key
from app.services.provider_errors import ProviderError, classify_http, inspect_payload

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset(
    {"succeeded", "partially_succeeded", "failed", "cancelled"}
)
TEXT_PROCESS_MAX_CHARS = 12_000
SPEAKER_MARKER = re.compile(r"\[(caller|agent)\s+(\d+:\d{2})\]")

VOICESANJ_USER_AGENT = "cbi-voice-analytics/httpx"


class VoiceSanjClient:
    """Async client for aiservice.voicesanj.ir (task queue + OpenAI-compatible chat)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base = (settings.voicesanj_base_url or "").rstrip("/")
        if not self._base:
            raise RuntimeError("VOICESANJ_BASE_URL is empty")
        key = normalize_api_key(settings.voicesanj_api_key)
        if not key:
            raise RuntimeError(
                "VoiceSanj API key is required; save it in admin model settings"
            )
        self._headers = {
            "Authorization": f"Bearer {key}",
            "User-Agent": VOICESANJ_USER_AGENT,
        }
        self._poll_interval = max(settings.voicesanj_poll_interval_seconds, 0.5)
        self._poll_timeout = max(settings.voicesanj_poll_timeout_seconds, 30.0)
        self._http_timeout = httpx.Timeout(
            connect=30.0,
            read=max(settings.llm_timeout_seconds, 120.0),
            write=120.0,
            pool=30.0,
        )
        self._llm_model = settings.voicesanj_llm_model
        self._correction_style = settings.voicesanj_text_correction_style

    async def validate_api_key(self) -> None:
        """Probe a user-scoped endpoint so regular ASR keys are accepted."""
        async with httpx.AsyncClient(timeout=self._http_timeout, http2=False) as client:
            response = await client.get(f"{self._base}/v1/models", headers=self._headers)
            classified = classify_http(response.status_code, response.text, kind="asr")
            if classified is not None:
                raise classified
            if response.status_code >= 400:
                raise RuntimeError(
                    f"voicesanj key rejected: HTTP {response.status_code}"
                )

    async def list_models(self) -> list[dict[str, Any]]:
        """Build workload-specific picker rows from the user API and public health."""
        async with httpx.AsyncClient(timeout=self._http_timeout, http2=False) as client:
            models_response = await client.get(
                f"{self._base}/v1/models",
                headers=self._headers,
                params={"kind": "all"},
            )
            classified = classify_http(
                models_response.status_code, models_response.text, kind="asr"
            )
            if classified is not None:
                raise classified
            if models_response.status_code >= 400:
                raise RuntimeError(
                    f"voicesanj models rejected: HTTP {models_response.status_code}"
                )
            try:
                models_payload: Any = models_response.json()
            except ValueError as exc:
                raise RuntimeError("voicesanj models response is not JSON") from exc

            health_response = await client.get(f"{self._base}/health")
            if health_response.status_code >= 400:
                raise RuntimeError(
                    f"voicesanj health rejected: HTTP {health_response.status_code}"
                )
            try:
                health_payload: Any = health_response.json()
            except ValueError as exc:
                raise RuntimeError("voicesanj health response is not JSON") from exc

        installed = {
            str(item).strip()
            for item in (health_payload.get("installed_models") or [])
            if str(item).strip()
        }
        rows = _openai_models(models_payload)
        known_ids = {row["id"] for row in rows}
        for row in rows:
            available = row.get("available")
            if not isinstance(available, bool):
                available = (
                    row["id"] in installed
                    or row.get("source") == "9router"
                    or row.get("owned_by") == "9router"
                )
            row["available"] = available
            row["status"] = row.get("status") or ("ready" if available else "not_installed")
            row["display_name"] = row.get("display_name") or row["id"]
            row["recommended"] = bool(row.get("recommended"))
        for model_id in sorted(installed - known_ids):
            rows.append(
                {
                    "id": model_id,
                    "kind": "unknown",
                    "display_name": model_id,
                    "available": True,
                    "status": "ready",
                    "recommended": False,
                }
            )
        return rows

    async def transcribe(
        self,
        path: Path,
        *,
        model: str,
        models: list[str] | None = None,
        response_format: str = "verbose_json",
        beam_size: int = 2,
        vad_filter: bool = True,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        model_ids = [item.strip() for item in (models or [model]) if item.strip()]
        if not model_ids:
            raise ProviderError(
                "asr_provider_model",
                "شناسه مدل پیاده‌سازی صوت خالی است.",
                retryable=False,
            )
        original_audio = path.read_bytes()
        audio = gzip.compress(original_audio, compresslevel=6, mtime=0)
        form: dict[str, str | list[str]] = {
            "response_format": response_format,
            "beam_size": str(beam_size),
            "vad_filter": "true" if vad_filter else "false",
            "audio_encoding": "gzip",
            "uncompressed_audio_bytes": str(len(original_audio)),
        }
        if models:
            form["models"] = model_ids
        else:
            form["model"] = model_ids[0]
        if prompt:
            form["prompt"] = prompt
        headers = {
            **self._headers,
            "Idempotency-Key": f"asr-{uuid4()}",
        }
        async with httpx.AsyncClient(timeout=self._http_timeout, http2=False) as client:
            response = await client.post(
                f"{self._base}{self._settings.aiservice_asr_path}",
                headers=headers,
                files={
                    "file": (
                        f"{path.name}.gz",
                        audio,
                        "application/gzip",
                    )
                },
                data=form,
            )
            if response.status_code not in (200, 202):
                classified = classify_http(response.status_code, response.text, kind="asr")
                if classified is not None:
                    raise classified
                raise RuntimeError(
                    f"voicesanj transcription rejected: HTTP {response.status_code}"
                )
            task = response.json()
            inspect_payload(task, kind="asr")
            result = (
                task
                if response.status_code == 200 and isinstance(task, dict) and (
                    "text" in task or "segments" in task
                )
                else await self._await_task(client, task, kind="asr")
            )
        return _unwrap_model_result(result)

    async def correct_text(self, text: str, *, model: str | None = None) -> str:
        source = text.strip()
        if not source:
            return text
        model_id = model or self._llm_model
        if len(source) <= TEXT_PROCESS_MAX_CHARS:
            return await self._correct_chunk(source, model=model_id)

        pieces: list[str] = []
        for chunk in _split_text(source, TEXT_PROCESS_MAX_CHARS):
            pieces.append(await self._correct_chunk(chunk, model=model_id))
        return "".join(pieces)

    async def _correct_chunk(self, text: str, *, model: str) -> str:
        body = {
            "text": text,
            "model": model,
            "operation": "correction",
            "style": self._correction_style,
        }
        headers = {
            **self._headers,
            "Idempotency-Key": f"txt-{uuid4()}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._http_timeout, http2=False) as client:
            response = await client.post(
                f"{self._base}/v1/text/process",
                headers=headers,
                json=body,
            )
            if response.status_code not in (200, 202):
                classified = classify_http(response.status_code, response.text, kind="llm")
                if classified is not None:
                    raise classified
                raise RuntimeError(
                    f"voicesanj text process rejected: HTTP {response.status_code}"
                )
            task = response.json()
            inspect_payload(task, kind="llm")
            result = await self._await_task(client, task, kind="llm")
        payload = _unwrap_model_result(result)
        corrected = str(payload.get("corrected_text") or "").strip()
        if not corrected:
            raise RuntimeError("voicesanj correction returned empty text")
        return corrected

    async def _await_task(
        self, client: httpx.AsyncClient, task: dict[str, Any], *, kind: str
    ) -> Any:
        task_id = str(task.get("task_id") or "")
        status_url = str(task.get("status_url") or "")
        if not status_url and task_id:
            status_url = f"/v1/tasks/{task_id}"
        if not status_url:
            raise RuntimeError("voicesanj task response missing status_url")
        status_url = _absolute(self._base, status_url)

        deadline = asyncio.get_running_loop().time() + self._poll_timeout
        latest = task
        while True:
            status = str(latest.get("status") or "")
            if status in TERMINAL_STATUSES:
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError(f"voicesanj task timed out ({task_id or status_url})")
            await asyncio.sleep(self._poll_interval)
            response = await client.get(status_url, headers=self._headers)
            classified = classify_http(response.status_code, response.text, kind=kind)
            if classified is not None:
                raise classified
            latest = response.json()
            inspect_payload(latest, kind=kind)

        if status in {"failed", "cancelled"}:
            detail = str(latest.get("error") or status)
            raise RuntimeError(f"voicesanj task {status}: {detail}")

        result_url = latest.get("result_url")
        if not result_url and task_id:
            result_url = f"/v1/tasks/{task_id}/result"
        if not result_url:
            raise RuntimeError("voicesanj task missing result_url")
        result_url = _absolute(self._base, str(result_url))
        response = await client.get(result_url, headers=self._headers)
        if response.status_code == 409:
            raise RuntimeError("voicesanj result not ready yet")
        classified = classify_http(response.status_code, response.text, kind=kind)
        if classified is not None:
            raise classified
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise RuntimeError("voicesanj result is not JSON") from exc
        inspect_payload(payload, kind=kind)
        return payload


async def correct_transcript(settings: Settings, text: str) -> str:
    """Correct a transcript only when explicitly requested by an operator."""
    if not text.strip():
        raise ValueError("transcript is empty")
    client = VoiceSanjClient(settings)
    async with asyncio.timeout(max(settings.voicesanj_correction_timeout_seconds, 0.01)):
        corrected = await client.correct_text(text)
    source_markers = SPEAKER_MARKER.findall(text)
    if source_markers and SPEAKER_MARKER.findall(corrected) != source_markers:
        raise ValueError("correction changed speaker markers")
    logger.info(
        "voicesanj correction applied",
        extra={"extra_fields": {"chars_in": len(text), "chars_out": len(corrected)}},
    )
    return corrected


def _openai_models(payload: Any) -> list[dict[str, Any]]:
    items: list[Any]
    if isinstance(payload, dict):
        nested = payload.get("data") or payload.get("models") or payload.get("items")
        items = nested if isinstance(nested, list) else []
    elif isinstance(payload, list):
        items = payload
    else:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or item.get("model") or "").strip()
        kind = str(item.get("kind") or "llm").strip().lower()
        key = (kind, model_id)
        if not model_id or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "id": model_id,
                "kind": kind,
                "display_name": str(item.get("display_name") or model_id),
                "description": str(item.get("description") or ""),
                "owned_by": str(item.get("owned_by") or ""),
                "source": str(item.get("source") or ""),
                "available": item.get("available"),
                "status": item.get("status"),
                "recommended": bool(item.get("recommended")),
                "language": item.get("language"),
                "model_id": item.get("model_id"),
                "architecture": item.get("architecture"),
                "license": item.get("license"),
            }
        )
    return rows


def _absolute(base: str, url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not url.startswith("/"):
        url = f"/{url}"
    return f"{base}{url}"


def _unwrap_model_result(payload: Any) -> dict[str, Any]:
    """Single-model results are flat; multi-model wraps runs under `results`."""
    if not isinstance(payload, dict):
        raise RuntimeError("voicesanj result is not a JSON object")
    results = payload.get("results")
    if isinstance(results, list) and results:
        for item in results:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "") not in {"succeeded", "partially_succeeded"}:
                continue
            nested = item.get("result")
            if isinstance(nested, dict):
                return nested
            if isinstance(nested, str) and nested.strip():
                return {"text": nested.strip()}
        errors = [
            str(item.get("error") or item.get("status"))
            for item in results
            if isinstance(item, dict)
        ]
        raise RuntimeError(f"voicesanj multi-model runs failed: {'; '.join(errors)[:400]}")
    return payload


def _split_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > limit and buf:
            chunks.append("".join(buf))
            buf = []
            size = 0
        if len(line) > limit and not buf:
            for start in range(0, len(line), limit):
                chunks.append(line[start : start + limit])
            continue
        buf.append(line)
        size += len(line)
    if buf:
        chunks.append("".join(buf))
    return chunks
