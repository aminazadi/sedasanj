"""Contracts for direct S3-compatible multipart audio uploads."""

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator, field_validator


class UploadCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    audio_bytes: int = Field(gt=0)
    content_type: str | None = Field(default=None, max_length=200)
    audio_encoding: Literal["identity", "gzip"] = "identity"
    uncompressed_audio_bytes: int | None = Field(default=None, gt=0)
    sha256: str | None = Field(default=None, description="Optional lowercase SHA-256; verified by the ASR worker before inference.")

    @model_validator(mode="after")
    def valid_encoding_size(self):
        if self.audio_encoding == "gzip" and self.uncompressed_audio_bytes is None:
            raise ValueError("uncompressed_audio_bytes is required for gzip audio")
        if self.audio_encoding == "identity" and self.uncompressed_audio_bytes is not None:
            raise ValueError("uncompressed_audio_bytes is only valid for gzip audio")
        return self

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value):
        if value is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("sha256 must contain exactly 64 hexadecimal characters")
        return value.lower() if value else None


class MultipartPart(BaseModel):
    part_number: int = Field(ge=1, le=10000)
    etag: str = Field(min_length=1, max_length=300)


class UploadCompleteRequest(BaseModel):
    parts: list[MultipartPart] = Field(min_length=1, max_length=10000)


class UploadTranscriptionRequest(BaseModel):
    model: str | None = Field(default=None, min_length=1)
    models: list[str] | None = Field(default=None, min_length=1)
    response_format: str = "json"
    prompt: str | None = Field(default=None, max_length=4000)
    beam_size: int = Field(default=2, ge=1, le=10)
    vad_filter: bool = True


class UploadResponse(BaseModel):
    upload_id: str
    status: str
    filename: str
    content_type: str | None = None
    audio_encoding: str = "identity"
    uncompressed_audio_bytes: int | None = None
    expected_bytes: int
    actual_bytes: int | None = None
    sha256: str | None = None
    created_at: str
    expires_at: str
    task_id: str | None = None
    error: str | None = None
    part_size: int
    part_url_endpoint: str | None = None
    complete_url: str | None = None


class UploadPartUrlResponse(BaseModel):
    part_number: int
    url: str
    expires_in: int
