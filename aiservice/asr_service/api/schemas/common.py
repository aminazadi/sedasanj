"""Shared schema primitives used by multiple endpoint contracts."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiSchema(BaseModel):
    """Base schema configured for clean and descriptive OpenAPI output."""

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class ErrorResponse(ApiSchema):
    """Standard FastAPI error envelope returned for unsuccessful requests."""

    detail: str = Field(
        description="Human-readable explanation of the error.",
        examples=["Task not found"],
    )


class ChatTaskError(ApiSchema):
    code: str = Field(description="Stable machine-readable chat-task error code.")
    message: str
    param: str | None = None


class ChatTaskErrorResponse(ApiSchema):
    error: ChatTaskError


class ValidationErrorItem(ApiSchema):
    """One invalid input reported by request validation."""

    loc: list[str | int] = Field(description="Path to the invalid field.")
    msg: str = Field(description="Human-readable validation message.")
    type: str = Field(description="Machine-readable validation error type.")
    input: Any | None = Field(
        default=None, description="Input value that failed validation."
    )


class ValidationErrorResponse(ApiSchema):
    """Validation errors produced before an endpoint is called."""

    detail: list[ValidationErrorItem]


class MessageResponse(ApiSchema):
    """Generic message response."""

    message: str


TaskStatus = Literal[
    "queued",
    "running",
    "retrying",
    "succeeded",
    "partially_succeeded",
    "failed",
    "cancelled",
]
