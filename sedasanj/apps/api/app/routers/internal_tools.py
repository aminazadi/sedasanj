from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import ValidationError

from app.errors import ApiError
from app.services import tool_gateway

router = APIRouter(prefix="/v1/internal/tools", tags=["internal"], include_in_schema=False)


@router.post("/{name}")
async def run_tool(name: str, request: Request) -> dict[str, Any]:
    """Signed webhook the assistant uses to run a tool; callers are never end users."""
    body = await request.body()
    await tool_gateway.verify(name, body, request.headers)
    try:
        payload = tool_gateway.GatewayRequest.model_validate_json(body)
    except ValidationError:
        raise ApiError("invalid_request", "درخواست ابزار ناقص است؛ پیام را دوباره بفرستید") from None
    return await tool_gateway.handle(name, payload)
