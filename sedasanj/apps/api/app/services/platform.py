from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings, normalize_api_key
from app.db import get_sessionmaker
from app.models import KpiConfiguration, PlatformSetting
from app.services.audio import DENOISER_MODELS, ENHANCEMENT_MODELS
from worker_llm.client import load_prompt

EXTRACT_PROMPT_KEY = "extract-fa-v3-prompt"
ASSISTANT_INSTRUCTIONS_KEY = "assistant-instructions"
OVERRIDE_KEYS = (
    "asr_model",
    "llm_provider",
    "llm_model",
    "chat_model",
    "prompt_version",
    "api_key",
    "voicesanj_base_url",
    "asr_provider",
    "asr_base_url",
    "asr_api_key",
    "audio_preprocessing_enabled",
    "audio_denoiser_model",
    "audio_enhancement_model",
    "analysis_concurrency",
    "decision_model",
    "decision_fallback_model",
    "decision_confidence_threshold",
    "decision_api_key",
    "embedding_base_url",
    "embedding_api_key",
    "embedding_model",
    "asr_route",
    "analysis_route",
    "chat_route",
    "decision_route",
    "embedding_route",
)

AISERVICE_ROUTES = {
    "asr_route": {
        "native": "/v1/audio/transcriptions",
        "ninerouter": "/v1/ninerouter/audio/transcriptions",
    },
    "analysis_route": {
        "durable": "/v1/chat/tasks",
    },
    "chat_route": {
        "durable": "/v1/chat/tasks",
        "synchronous": "/v1/chat/completions",
        "ninerouter": "/v1/ninerouter/chat/completions",
    },
    "decision_route": {"typed": "/v1/decisions"},
    "embedding_route": {"ninerouter": "/v1/ninerouter/embeddings"},
}

__all__ = (
    "OVERRIDE_KEYS",
    "effective_models",
    "effective_extract_prompt",
    "effective_assistant_instructions",
    "mask_api_key",
    "normalize_api_key",
    "resolve_provider_settings",
    "settings_public_view",
)


async def effective_extract_prompt(session: AsyncSession, prompt_version: str) -> str:
    """Return the admin-managed main prompt, falling back to its packaged default."""
    if prompt_version == "extract-fa-v3":
        if get_settings().tenant_databases_enabled:
            async with get_sessionmaker()() as control:
                row = await control.get(PlatformSetting, EXTRACT_PROMPT_KEY)
        else:
            row = await session.get(PlatformSetting, EXTRACT_PROMPT_KEY)
        prompt = (
            row.value.strip()
            if row is not None and row.value.strip()
            else load_prompt(prompt_version)
        )
        configuration = (
            await session.execute(
                select(KpiConfiguration)
                .where(KpiConfiguration.active.is_(True))
                .order_by(KpiConfiguration.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if configuration is not None:
            stages = ", ".join(configuration.settings.get("funnel_stages", []))
            objections = ", ".join(configuration.settings.get("objection_taxonomy", []))
            return (
                f"{prompt}\n\nActive sales taxonomy version: "
                f"{configuration.settings.get('taxonomy_version', 1)}. "
                f"Allowed funnel_stage values: {stages}. "
                f"Allowed objection values: {objections}. Use other for an unmatched objection."
            )
        return prompt
    return load_prompt(prompt_version)


async def effective_assistant_instructions(session: AsyncSession) -> str:
    if get_settings().tenant_databases_enabled:
        async with get_sessionmaker()() as control:
            row = await control.get(PlatformSetting, ASSISTANT_INSTRUCTIONS_KEY)
    else:
        row = await session.get(PlatformSetting, ASSISTANT_INSTRUCTIONS_KEY)
    return row.value.strip() if row is not None else ""


def _default_asr_model(settings: Settings) -> str:
    if settings.asr_engine == "voicesanj":
        return settings.voicesanj_asr_model
    if settings.asr_engine == "whisper":
        return settings.whisper_model
    return settings.asr_model_name


def _default_llm_model(settings: Settings) -> str:
    if settings.llm_client == "voicesanj":
        return settings.voicesanj_llm_model
    return settings.llm_model


def mask_api_key(value: str) -> str:
    secret = normalize_api_key(value)
    if not secret:
        return ""
    if len(secret) <= 4:
        return "••••"
    return f"••••{secret[-4:]}"


def normalize_provider_base_url(raw: str) -> str:
    """Accept only a scheme and host/IP (optional port), never a path or credentials."""
    value = raw.strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("آدرس سرویس معتبر نیست") from exc
    host = parsed.hostname
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
        or any(char.isspace() for char in value)
        or port == 0
    ):
        raise ValueError("فقط آدرس پایه شامل http(s)، دامنه یا IP و پورت اختیاری مجاز است")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or any(
            not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
            for label in host.split(".")
        ):
            raise ValueError("دامنه سرویس معتبر نیست") from None
    else:
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise ValueError("آدرس IP سرویس معتبر نیست")
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    normalized = f"{parsed.scheme}://{authority}"
    if normalized == "http://aiservice.voicesanj.ir":
        return "https://aiservice.voicesanj.ir"
    return normalized


async def effective_models(session: AsyncSession) -> dict[str, str]:
    """Admin-managed model settings (§ admin panel) with env defaults as fallback.

    The provider `api_key` is settings-only: env `VOICESANJ_API_KEY` is ignored.
    """
    settings = get_settings()
    values = {
        "asr_model": _default_asr_model(settings),
        "llm_provider": "voicesanj",
        "llm_model": _default_llm_model(settings),
        "chat_model": _default_llm_model(settings),
        "prompt_version": settings.prompt_version,
        "api_key": "",
        "voicesanj_base_url": settings.voicesanj_base_url,
        "asr_provider": "voicesanj",
        "asr_base_url": settings.voicesanj_base_url,
        "asr_api_key": "",
        "audio_preprocessing_enabled": str(settings.audio_preprocessing_enabled).lower(),
        "audio_denoiser_model": settings.audio_denoiser_model,
        "audio_enhancement_model": settings.audio_enhancement_model,
        "analysis_concurrency": str(settings.analysis_concurrency),
        "decision_model": "gliner2_5_multi_decide",
        "decision_fallback_model": "laya_multilingual",
        "decision_confidence_threshold": "0.72",
        "decision_api_key": "",
        "embedding_base_url": settings.embedding_base_url or settings.voicesanj_base_url,
        "embedding_api_key": "",
        "embedding_model": settings.embedding_model,
        "asr_route": "native",
        "analysis_route": "durable",
        "chat_route": "durable",
        "decision_route": "typed",
        "embedding_route": "ninerouter",
    }
    settings_session = session
    if get_settings().tenant_databases_enabled:
        settings_session = get_sessionmaker()()
    try:
        scalar_rows = (
            await settings_session.execute(
                select(PlatformSetting).where(PlatformSetting.key.in_(OVERRIDE_KEYS))
            )
        ).scalars()
    finally:
        if settings_session is not session:
            await settings_session.close()
    rows = scalar_rows.all() if hasattr(scalar_rows, "all") else list(scalar_rows)
    row_keys = {row.key for row in rows}
    for row in rows:
        values[row.key] = (
            normalize_api_key(row.value)
            if row.key in {"api_key", "asr_api_key", "decision_api_key", "embedding_api_key"}
            else row.value
        )
    shared_key = normalize_api_key(values["api_key"])
    values["llm_provider"] = "voicesanj"
    values["asr_provider"] = "voicesanj"
    values["asr_api_key"] = shared_key
    values["decision_api_key"] = shared_key
    values["embedding_api_key"] = shared_key
    values["asr_base_url"] = values["voicesanj_base_url"]
    values["embedding_base_url"] = values["voicesanj_base_url"]
    values["voicesanj_base_url"] = normalize_provider_base_url(values["voicesanj_base_url"])
    values["asr_base_url"] = normalize_provider_base_url(values["asr_base_url"])
    values["embedding_base_url"] = normalize_provider_base_url(values["embedding_base_url"])
    if "chat_model" not in row_keys:
        values["chat_model"] = values["llm_model"]
    return values


async def settings_public_view(session: AsyncSession) -> dict[str, object]:
    """Settings payload safe for the admin UI (API key is never returned in full)."""
    values = await effective_models(session)
    api_key = values.pop("api_key", "") or ""
    asr_api_key = values.pop("asr_api_key", "") or ""
    decision_api_key = values.pop("decision_api_key", "") or ""
    embedding_api_key = values.pop("embedding_api_key", "") or ""
    return {
        "asr_model": values["asr_model"],
        "llm_provider": values["llm_provider"],
        "llm_model": values["llm_model"],
        "chat_model": values["chat_model"],
        "prompt_version": values["prompt_version"],
        "extract_prompt": await effective_extract_prompt(session, values["prompt_version"]),
        "assistant_instructions": await effective_assistant_instructions(session),
        "api_key_configured": bool(api_key.strip()),
        "api_key_hint": mask_api_key(api_key),
        "voicesanj_base_url": values["voicesanj_base_url"],
        "asr_provider": values["asr_provider"],
        "asr_base_url": values["asr_base_url"],
        "asr_api_key_configured": bool(asr_api_key.strip()),
        "asr_api_key_hint": mask_api_key(asr_api_key),
        "local_asr_available": get_settings().asr_engine not in {"voicesanj", "whisper"},
        "audio_preprocessing_enabled": _as_bool(values["audio_preprocessing_enabled"]),
        "audio_denoiser_model": values["audio_denoiser_model"],
        "audio_enhancement_model": values["audio_enhancement_model"],
        "analysis_concurrency": int(values["analysis_concurrency"]),
        "decision_model": values["decision_model"],
        "decision_fallback_model": values["decision_fallback_model"],
        "decision_confidence_threshold": float(values["decision_confidence_threshold"]),
        "decision_api_key_configured": bool(decision_api_key.strip()),
        "decision_api_key_hint": mask_api_key(decision_api_key),
        "embedding_base_url": values["embedding_base_url"],
        "embedding_model": values["embedding_model"],
        "embedding_api_key_configured": bool(embedding_api_key.strip()),
        "embedding_api_key_hint": mask_api_key(embedding_api_key),
        "asr_route": values["asr_route"],
        "analysis_route": values["analysis_route"],
        "chat_route": values["chat_route"],
        "decision_route": values["decision_route"],
        "embedding_route": values["embedding_route"],
        "audio_denoiser_models": _audio_catalog(DENOISER_MODELS),
        "audio_enhancement_models": _audio_catalog(ENHANCEMENT_MODELS),
    }


async def resolve_provider_settings(session: AsyncSession) -> Settings:
    """Env settings overlaid with admin platform overrides for provider calls."""
    base = get_settings()
    overrides = await effective_models(session)
    api_key = normalize_api_key(overrides.get("api_key")) or None
    asr_api_key = normalize_api_key(overrides.get("asr_api_key")) or None
    decision_api_key = normalize_api_key(overrides.get("decision_api_key")) or None
    embedding_api_key = normalize_api_key(overrides.get("embedding_api_key")) or None
    asr_engine = "voicesanj"
    return base.model_copy(
        update={
            "asr_engine": asr_engine,
            "asr_model_name": overrides["asr_model"],
            "whisper_model": overrides["asr_model"],
            "voicesanj_asr_model": overrides["asr_model"],
            "llm_client": "voicesanj",
            "llm_model": overrides["llm_model"],
            "voicesanj_llm_model": overrides["llm_model"],
            "prompt_version": overrides["prompt_version"],
            "audio_preprocessing_enabled": _as_bool(overrides["audio_preprocessing_enabled"]),
            "audio_denoiser_model": overrides["audio_denoiser_model"],
            "audio_enhancement_model": overrides["audio_enhancement_model"],
            "analysis_concurrency": int(overrides["analysis_concurrency"]),
            # Always replace env keys so only the Settings-panel secret is used.
            "voicesanj_api_key": api_key,
            "voicesanj_base_url": overrides["voicesanj_base_url"],
            "openai_api_key": api_key,
            "asr_provider_base_url": overrides["asr_base_url"],
            "asr_provider_api_key": asr_api_key,
            "decision_api_key": decision_api_key,
            "decision_model": overrides["decision_model"],
            "decision_fallback_model": overrides["decision_fallback_model"],
            "decision_confidence_threshold": float(overrides["decision_confidence_threshold"]),
            "embedding_base_url": overrides["embedding_base_url"],
            "embedding_api_key": embedding_api_key,
            "embedding_model": overrides["embedding_model"],
            "aiservice_asr_path": AISERVICE_ROUTES["asr_route"][overrides["asr_route"]],
            "aiservice_analysis_path": AISERVICE_ROUTES["analysis_route"][overrides["analysis_route"]],
            "aiservice_chat_path": AISERVICE_ROUTES["chat_route"][overrides["chat_route"]],
            "aiservice_decision_path": AISERVICE_ROUTES["decision_route"][overrides["decision_route"]],
            "aiservice_embedding_path": AISERVICE_ROUTES["embedding_route"][overrides["embedding_route"]],
        }
    )


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _audio_catalog(models: dict[str, tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"id": model_id, "label": label, "description": description}
        for model_id, (label, description) in models.items()
    ]
