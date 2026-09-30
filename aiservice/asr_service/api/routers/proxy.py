"""Download proxy configuration and connectivity endpoints."""

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException

from asr_service.infrastructure.proxy import public_config, save_config, test_connection
from asr_service.infrastructure.storage import audit

from ..dependencies import authorize_admin
from ..openapi import documented_responses
from ..schemas.common import ErrorResponse
from ..schemas.requests import ProxyConfigRequest
from ..schemas.responses import ProxyConfigResponse, ProxyTestResponse

router = APIRouter(prefix="/api/proxy", tags=["Download proxy"], dependencies=[Depends(authorize_admin)])


@router.get(
    "",
    response_model=ProxyConfigResponse,
    summary="Get download proxy configuration",
    description="Returns the saved model-download proxy configuration with any password redacted, plus the most recent test result.",
    responses=documented_responses(),
)
def get_proxy():
    """Return the credential-safe public proxy configuration."""

    return public_config()


@router.put(
    "",
    response_model=ProxyConfigResponse,
    summary="Replace download proxy configuration",
    description="Validates and saves an HTTP(S), SOCKS5, or SOCKS5H proxy URI. Saving clears the previous connectivity-test result.",
    responses=documented_responses(
        include_validation=True,
        **{"422": {"model": ErrorResponse, "description": "The enabled proxy URI is missing, malformed, or unsupported."}},
    ),
)
def put_proxy(body: ProxyConfigRequest):
    """Validate, persist, and safely return the download proxy configuration."""

    uri = body.uri.strip()
    if body.enabled and not uri:
        raise HTTPException(422, "Proxy URI is required when enabled")
    if uri:
        try:
            parsed = urlsplit(uri)
            port = parsed.port
        except ValueError:
            raise HTTPException(422, "Proxy URI is invalid")
        if parsed.scheme not in {"http", "https", "socks5", "socks5h"} or not parsed.hostname or port is None:
            raise HTTPException(422, "Proxy URI must include a supported scheme, host and port")
    result = save_config(body.enabled, uri)
    audit("proxy_config_updated", detail=f"enabled={body.enabled}; scheme={urlsplit(uri).scheme if uri else 'none'}")
    return result


@router.post(
    "/test",
    response_model=ProxyTestResponse,
    summary="Test the download proxy",
    description="Attempts a real request to Hugging Face through the saved proxy and persists latency, HTTP status, and a credential-safe diagnostic message.",
    responses=documented_responses(),
)
def proxy_test():
    """Test connectivity through the configured download proxy."""

    return test_connection()
