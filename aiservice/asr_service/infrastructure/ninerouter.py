"""Persisted, secret-safe configuration and OpenAI-compatible 9Router client."""

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests
from cryptography.fernet import Fernet, InvalidToken

from .storage import execute, now, row

SETTING_KEY = "ninerouter_config"
MODELS_KEY = "ninerouter_models"
DEFAULT_URL = "http://127.0.0.1:20128"
SECRET_ENV = "ASR_9ROUTER_SECRETS_KEY"


class NineRouterError(RuntimeError):
    def __init__(self, message, status_code=None, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def normalize_url(value):
    value = (value or DEFAULT_URL).strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("9Router URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("9Router URL must be an HTTP(S) origin without credentials, query, or fragment")
    if parsed.path not in {"", "/", "/v1"}:
        raise ValueError("9Router URL must be its origin or /v1")
    host = parsed.hostname.lower()
    authority = f"[{host}]" if ":" in host and not host.startswith("[") else host
    if port is not None:
        authority += f":{port}"
    return f"{parsed.scheme}://{authority}"


def _fernet():
    key = os.getenv(SECRET_ENV, "").strip().encode()
    if not key:
        raise NineRouterError(f"{SECRET_ENV} must be configured before saving a 9Router API key")
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise NineRouterError(f"{SECRET_ENV} must be a valid Fernet key") from exc


def _defaults():
    return {
        "url": DEFAULT_URL,
        "api_key_encrypted": "",
        "asr_enabled": False,
        "asr_model": "",
        "text_enabled": False,
        "text_model": "",
        "connect_timeout_seconds": 10,
        "read_timeout_seconds": 300,
    }


def _stored():
    try:
        item = row("SELECT value FROM settings WHERE key=?", (SETTING_KEY,))
    except sqlite3.OperationalError:
        return _defaults()
    if not item:
        return _defaults()
    try:
        data = json.loads(item["value"])
    except (TypeError, ValueError):
        data = {}
    return _defaults() | {key: value for key, value in data.items() if key in _defaults()}


def public_config():
    data = _stored()
    return {
        "url": data["url"],
        "has_api_key": bool(data["api_key_encrypted"]),
        "asr_enabled": bool(data["asr_enabled"]),
        "asr_model": data["asr_model"],
        "text_enabled": bool(data["text_enabled"]),
        "text_model": data["text_model"],
        "connect_timeout_seconds": data["connect_timeout_seconds"],
        "read_timeout_seconds": data["read_timeout_seconds"],
    }


def cached_models():
    try:
        item = row("SELECT value FROM settings WHERE key=?", (MODELS_KEY,))
    except sqlite3.OperationalError:
        return []
    if not item:
        return []
    try:
        return json.loads(item["value"])["models"]
    except (TypeError, ValueError, KeyError):
        return []


def save_models(models):
    execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (MODELS_KEY, json.dumps({"models": models, "synced_at": now()})))


def _secret(data):
    token = data.get("api_key_encrypted", "")
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise NineRouterError("Stored 9Router API key cannot be decrypted") from exc


def save_config(body):
    current = _stored()
    api_key = body.get("api_key")
    data = current | {key: value for key, value in body.items() if key != "api_key"}
    data["url"] = normalize_url(data["url"])
    for name in ("asr_model", "text_model"):
        data[name] = data[name].strip()
    if api_key:
        data["api_key_encrypted"] = _fernet().encrypt(api_key.encode()).decode()
    if (data["asr_enabled"] or data["text_enabled"]) and not data["api_key_encrypted"]:
        raise NineRouterError("A 9Router API key is required when a 9Router provider is enabled")
    if data["asr_enabled"] and not data["asr_model"]:
        raise NineRouterError("A 9Router ASR model is required when ASR is enabled")
    if data["text_enabled"] and not data["text_model"]:
        raise NineRouterError("A 9Router text model is required when Text/Chat is enabled")
    execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (SETTING_KEY, json.dumps(data)))
    return public_config()


@dataclass(frozen=True)
class ProviderSettings:
    url: str
    api_key: str
    asr_enabled: bool
    asr_model: str
    text_enabled: bool
    text_model: str
    timeout: tuple[int, int]


def resolve_settings(include_secret=False):
    data = _stored()
    enabled = bool(data["asr_enabled"] or data["text_enabled"])
    return ProviderSettings(
        url=normalize_url(data["url"]), api_key=_secret(data) if (enabled or include_secret) else "",
        asr_enabled=bool(data["asr_enabled"]), asr_model=data["asr_model"],
        text_enabled=bool(data["text_enabled"]), text_model=data["text_model"],
        timeout=(int(data["connect_timeout_seconds"]), int(data["read_timeout_seconds"])),
    )


def configured_model(kind):
    settings = resolve_settings()
    if kind == "asr" and settings.asr_enabled:
        return settings.asr_model
    if kind == "llm" and settings.text_enabled:
        return settings.text_model
    return None


def configured_models(kind):
    """Return every cached model executable through the enabled 9Router route."""
    settings = resolve_settings()
    enabled = (
        settings.asr_enabled
        if kind == "asr"
        else settings.text_enabled
        if kind == "llm"
        else settings.asr_enabled or settings.text_enabled
    )
    if not enabled:
        return set()
    models = {
        str(item.get("id") or "").strip()
        for item in cached_models()
        if item.get("kind") == kind and str(item.get("id") or "").strip()
    }
    selected = (
        settings.asr_model
        if kind == "asr"
        else settings.text_model
        if kind == "llm"
        else ""
    )
    if selected:
        models.add(selected)
    return models


def is_configured_model(kind, model_id):
    return model_id in configured_models(kind)


def _safe_detail(response):
    try:
        detail = response.json().get("error") or response.json().get("detail") or response.text
    except (ValueError, AttributeError):
        detail = response.text
    return re.sub(r"(?i)(bearer\s+|sk-[\w-]+)[^\s,;\"]+", r"\1[redacted]", str(detail))[:500]


class NineRouterClient:
    def __init__(self, settings):
        self.settings = settings
        if not settings.api_key:
            raise NineRouterError("9Router API key is not configured")

    def _request(self, method, path, **kwargs):
        started = time.monotonic()
        try:
            response = requests.request(
                method, self.settings.url + path,
                headers={"Authorization": f"Bearer {self.settings.api_key}"} | kwargs.pop("headers", {}),
                timeout=self.settings.timeout, **kwargs,
            )
        except requests.Timeout as exc:
            raise NineRouterError("9Router request timed out", retryable=True) from exc
        except requests.RequestException as exc:
            raise NineRouterError(f"9Router network error: {type(exc).__name__}", retryable=True) from exc
        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise NineRouterError(f"9Router HTTP {response.status_code}: {_safe_detail(response)}", response.status_code, retryable)
        return response, int((time.monotonic() - started) * 1000)

    def health_and_models(self):
        health, latency = self._request("GET", "/api/health")
        self._request("GET", "/v1/models")
        return {"state": "connected", "message": "9Router connection verified", "checked_at": now(), "latency_ms": latency, "health": health.json()}

    def models(self, kind="chat"):
        path = "/v1/models" if kind == "chat" else f"/v1/models/{kind}"
        response, _ = self._request("GET", path)
        data = response.json().get("data", [])
        return [{"id": str(item.get("id")), "owned_by": item.get("owned_by", "9router")} for item in data if item.get("id")]

    def sync_models(self):
        groups = {"llm": "chat", "asr": "stt", "decision": "decision", "tts": "tts", "embedding": "embedding", "image": "image", "video": "video", "web": "web", "vision": "image-to-text"}
        result = []
        for kind, endpoint in groups.items():
            try:
                result.extend({**model, "kind": kind, "source": "9router"} for model in self.models(endpoint))
            except NineRouterError as error:
                if error.status_code != 404:
                    raise
        unique = {f"{model['kind']}:{model['id']}": model for model in result}
        return list(unique.values())

    def chat(self, model, messages, options):
        response, _ = self._request("POST", "/v1/chat/completions", json={"model": model, "messages": messages, **options})
        payload = response.json()
        if not isinstance(payload.get("choices"), list):
            raise NineRouterError("9Router returned an invalid chat completion")
        return payload

    def transcribe(self, model, path, prompt=None):
        response_format = (
            "json" if "gpt-4o-transcribe" in model.lower() else "verbose_json"
        )
        with Path(path).open("rb") as audio:
            response, _ = self._request(
                "POST", "/v1/audio/transcriptions",
                data={
                    "model": model,
                    "language": "fa",
                    "response_format": response_format,
                    **({"prompt": prompt} if prompt else {}),
                },
                files={"file": (Path(path).name, audio)},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise NineRouterError("9Router returned an invalid transcription response") from exc
        text = str(payload.get("text") or "").strip()
        if not text:
            raise NineRouterError("9Router transcription response did not contain text")
        duration = payload.get("duration")
        segments = payload.get("segments") or [{"id": 0, "start": 0, "end": duration or 0, "text": text}]
        return {"text": text, "language": payload.get("language") or "fa", "duration": duration, "duration_after_vad": duration, "model": model, "segments": segments}
