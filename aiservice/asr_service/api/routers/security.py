"""Administrator endpoints for issued API keys and live CORS/network policy."""

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from asr_service.infrastructure.storage import execute, now, row, rows
from asr_service.infrastructure.ninerouter import configured_models
from ..dependencies import authorize_admin, issue_key
from ..schemas.responses import RequestFailurePageResponse

router = APIRouter(prefix="/api", dependencies=[Depends(authorize_admin)])
VALID_SCOPES = {"inference", "chat", "transcription", "text", "decision", "embedding"}


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["inference"])
    models: list[str] | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100000)
    expires_at: datetime | None = None

    @field_validator("scopes")
    @classmethod
    def scopes_are_known(cls, value):
        if not value or not set(value) <= VALID_SCOPES:
            raise ValueError(f"scopes must be selected from {sorted(VALID_SCOPES)}")
        return list(dict.fromkeys(value))

    @field_validator("models")
    @classmethod
    def unique_models(cls, value):
        return list(dict.fromkeys(value)) if value is not None else None

    @field_validator("expires_at")
    @classmethod
    def normalized_expiry(cls, value):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class ApiKeyUpdate(BaseModel):
    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    scopes: list[str] | None = None
    models: list[str] | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100000)
    expires_at: datetime | None = None

    _scopes_are_known = field_validator("scopes")(ApiKeyCreate.scopes_are_known.__func__)
    _unique_models = field_validator("models")(ApiKeyCreate.unique_models.__func__)
    _normalized_expiry = field_validator("expires_at")(ApiKeyCreate.normalized_expiry.__func__)

    @model_validator(mode="after")
    def non_nullable_fields(self):
        for name in ("enabled", "name", "scopes"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


def public_key(item):
    return {k: item.get(k) for k in ("id", "name", "key_prefix", "enabled", "rate_limit_per_minute", "expires_at", "created_at", "last_used_at", "revoked_at")} | {
        "scopes": json.loads(item["scopes_json"] or "[]"),
        "models": json.loads(item["models_json"]) if item.get("models_json") else None,
    }


@router.get("/keys", summary="List issued API keys", description="Lists safe metadata; secret key values are never returned.")
def list_keys():
    return [public_key(item) for item in rows("SELECT * FROM api_keys ORDER BY id DESC")]


@router.post("/keys", status_code=201, summary="Create an API key", description="Creates a non-admin API key. The secret is returned exactly once.")
def create_key(body: ApiKeyCreate):
    from asr_service.domain.catalog import CATALOG
    allowed_models = set(CATALOG) | configured_models("asr") | configured_models("llm")
    if body.models is not None and any(model not in allowed_models for model in body.models):
        raise HTTPException(400, "models contains an unknown model id")
    secret, prefix, digest = issue_key()
    key_id = execute("""INSERT INTO api_keys(name,key_prefix,key_hash,enabled,scopes_json,models_json,rate_limit_per_minute,expires_at,created_at)
      VALUES(?,?,?,1,?,?,?,?,?)""", (body.name, prefix, digest, json.dumps(body.scopes), json.dumps(body.models) if body.models is not None else None,
      body.rate_limit_per_minute, body.expires_at.isoformat() if body.expires_at else None, now()))
    return {**public_key(row("SELECT * FROM api_keys WHERE id=?", (key_id,))), "api_key": secret}


@router.patch("/keys/{key_id}", summary="Enable or block an API key", description="Immediately enables or blocks a non-admin issued API key.")
def update_key(key_id: int, body: ApiKeyUpdate):
    if not row("SELECT id FROM api_keys WHERE id=?", (key_id,)):
        raise HTTPException(404, "API key not found")
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(400, "At least one API key setting is required")
    if "models" in values:
        from asr_service.domain.catalog import CATALOG
        requested_models = values.pop("models")
        allowed_models = set(CATALOG) | configured_models("asr") | configured_models("llm")
        if requested_models is not None and any(model not in allowed_models for model in requested_models):
            raise HTTPException(400, "models contains an unknown model id")
        values["models_json"] = json.dumps(requested_models) if requested_models is not None else None
    if "scopes" in values:
        values["scopes_json"] = json.dumps(values.pop("scopes"))
    if "expires_at" in values:
        values["expires_at"] = values["expires_at"].isoformat() if values["expires_at"] else None
    if "enabled" in values:
        enabled = values["enabled"]
        values["enabled"] = int(enabled)
        values["revoked_at"] = None if enabled else now()
    assignments = ",".join(f"{name}=?" for name in values)
    execute(f"UPDATE api_keys SET {assignments} WHERE id=?", (*values.values(), key_id))
    return public_key(row("SELECT * FROM api_keys WHERE id=?", (key_id,)))


@router.delete("/keys/{key_id}", status_code=204, summary="Delete an API key", description="Permanently deletes an issued non-admin API key.")
def delete_key(key_id: int):
    if not row("SELECT id FROM api_keys WHERE id=?", (key_id,)):
        raise HTTPException(404, "API key not found")
    execute("DELETE FROM api_keys WHERE id=?", (key_id,))
    return Response(status_code=204)


class CorsPolicy(BaseModel):
    allowed_origins: list[str] = Field(default_factory=list)
    allowed_ips: list[str] = Field(default_factory=list, description="IPv4/IPv6 addresses or CIDR networks allowed to call /v1.")
    allow_credentials: bool = False
    allowed_methods: list[str] = Field(default_factory=lambda: ["GET", "POST", "DELETE", "OPTIONS"])
    allowed_headers: list[str] = Field(default_factory=lambda: ["Authorization", "Content-Type", "Idempotency-Key"])

    @field_validator("allowed_origins")
    @classmethod
    def valid_origins(cls, values):
        normalized = []
        for value in values:
            if value == "*":
                normalized.append(value)
                continue
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
                raise ValueError(f"Invalid origin: {value}")
            normalized.append(f"{parsed.scheme}://{parsed.netloc}")
        return list(dict.fromkeys(normalized))

    @field_validator("allowed_methods")
    @classmethod
    def valid_methods(cls, values):
        values = [value.upper() for value in values]
        if not values or any(not re.fullmatch(r"[A-Z]+", value) for value in values):
            raise ValueError("allowed_methods contains an invalid method")
        return list(dict.fromkeys(values))

    @field_validator("allowed_headers")
    @classmethod
    def valid_headers(cls, values):
        if any(not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", value) for value in values):
            raise ValueError("allowed_headers contains an invalid header")
        return list(dict.fromkeys(values))


DEFAULT_CORS = CorsPolicy()


def get_cors_policy():
    saved = row("SELECT value FROM settings WHERE key='cors_policy'")
    return CorsPolicy.model_validate_json(saved["value"]) if saved else DEFAULT_CORS


@router.get("/cors", summary="Get CORS and IP policy", description="Returns the live browser-origin and client-IP allowlists.")
def get_cors():
    return get_cors_policy()


@router.put("/cors", summary="Update CORS and IP policy", description="Atomically replaces the policy; changes apply without a restart.")
def put_cors(body: CorsPolicy):
    import ipaddress
    try:
        for value in body.allowed_ips:
            ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid IP or CIDR: {exc}")
    execute("INSERT OR REPLACE INTO settings(key,value) VALUES('cors_policy',?)", (body.model_dump_json(),))
    return body


@router.get(
    "/request-failures",
    response_model=RequestFailurePageResponse,
    summary="List unsuccessful API requests and processing outcomes",
    description="Returns every persisted unsuccessful /v1 response plus failed, partially failed, and cancelled asynchronous tasks.",
)
@router.get(
    "/security-rejections",
    response_model=RequestFailurePageResponse,
    summary="List unsuccessful requests (compatibility alias)",
    description="Compatibility alias for /api/request-failures. Includes network-policy, authentication, validation, capacity, processing, and other unsuccessful outcomes.",
    deprecated=True,
)
def list_security_rejections(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    reason: str | None = Query(default=None),
    phase: str | None = Query(default=None),
    status_code: int | None = Query(default=None, ge=400, le=599),
):
    # Direct callers (including maintenance scripts) receive FastAPI's Query
    # sentinel for omitted optional parameters; normalize it before SQL.
    page = page if isinstance(page, int) else 1
    page_size = page_size if isinstance(page_size, int) else 50
    reason = reason if isinstance(reason, str) else None
    phase = phase if isinstance(phase, str) else None
    status_code = status_code if isinstance(status_code, int) else None
    clauses = []
    args = []
    for column, value in (("reason", reason), ("phase", phase), ("status_code", status_code)):
        if value is not None:
            clauses.append(f"{column}=?")
            args.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    total = row(f"SELECT COUNT(*) AS count FROM request_failures{where}", tuple(args))["count"]
    items = rows(
        f"""SELECT id,created_at,status_code,phase,reason,detail,client_ip,origin,method,path,
        query_string,x_forwarded_for,x_real_ip,forwarded,user_agent,requested_method,
        requested_headers,task_id,usage_id FROM request_failures{where}
        ORDER BY id DESC LIMIT ? OFFSET ?""",
        (*args, page_size, (page - 1) * page_size),
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}
