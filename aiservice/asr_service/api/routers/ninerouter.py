"""Administrator controls for the external 9Router provider."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from asr_service.infrastructure.ninerouter import NineRouterClient, NineRouterError, public_config, resolve_settings, save_config, save_models
from asr_service.infrastructure.storage import audit
from ..dependencies import authorize_admin

router = APIRouter(prefix="/api/ninerouter", tags=["9Router"], dependencies=[Depends(authorize_admin)])


class NineRouterConfigRequest(BaseModel):
    url: str = Field(default="http://127.0.0.1:20128", max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)
    asr_enabled: bool = False
    asr_model: str = Field(default="", max_length=200)
    text_enabled: bool = False
    text_model: str = Field(default="", max_length=200)
    connect_timeout_seconds: int = Field(default=10, ge=1, le=60)
    read_timeout_seconds: int = Field(default=300, ge=1, le=3600)

    @field_validator("api_key")
    @classmethod
    def strip_key(cls, value):
        return value.strip() if value else None


def _error(error):
    status = error.status_code if error.status_code in {401, 403, 404, 422} else 422
    raise HTTPException(status, str(error))


@router.get("")
def get_config():
    return public_config()


@router.put("")
def put_config(body: NineRouterConfigRequest):
    try:
        result = save_config(body.model_dump())
    except (NineRouterError, ValueError) as error:
        _error(error)
    audit("ninerouter_config_updated", detail=f"asr_enabled={result['asr_enabled']}; text_enabled={result['text_enabled']}")
    return result


@router.post("/test")
def test_config():
    try:
        return NineRouterClient(resolve_settings(include_secret=True)).health_and_models()
    except NineRouterError as error:
        _error(error)


@router.get("/models/{kind}")
def get_models(kind: str):
    if kind not in {"chat", "stt"}:
        raise HTTPException(422, "kind must be chat or stt")
    try:
        return {"data": NineRouterClient(resolve_settings(include_secret=True)).models(kind)}
    except NineRouterError as error:
        _error(error)


@router.post("/models/sync")
def sync_models():
    try:
        models = NineRouterClient(resolve_settings(include_secret=True)).sync_models()
        save_models(models)
        audit("ninerouter_models_synced", detail=f"count={len(models)}")
        return {"data": models, "count": len(models)}
    except NineRouterError as error:
        _error(error)


proxy_router = APIRouter(prefix="/v1/ninerouter", tags=["9Router proxy"])
ALLOWED_PATHS = {
    "decisions",
    "embeddings",
    "audio/speech",
    "images/generations",
    "images/edits",
    "videos/generations",
    "videos/edits",
    "search",
    "fetch",
    "responses",
    "messages",
    "completions",
    "chat/completions",
}


@proxy_router.api_route("/{path:path}", methods=["GET", "POST", "DELETE"])
async def proxy_request(path: str, request: Request):
    if path not in ALLOWED_PATHS:
        raise HTTPException(404, "Unsupported 9Router capability")
    from ..dependencies import authorize, require_access
    principal = authorize(request.headers.get("Authorization"))
    require_access(principal, "inference")
    try:
        settings = resolve_settings(include_secret=True)
        client = NineRouterClient(settings)
        response, _ = client._request(request.method, "/v1/" + path, data=await request.body(), headers={"Content-Type": request.headers.get("Content-Type", "application/json")})
    except NineRouterError as error:
        _error(error)
    return Response(response.content, status_code=response.status_code, media_type=response.headers.get("Content-Type"))
