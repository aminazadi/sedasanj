"""Request models, grouped independently from response contracts."""

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
import ipaddress
import re
from typing import Any, Literal


class TextProcessRequest(BaseModel):
    """JSON body accepted when scheduling Persian text post-processing."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "text": "متن خام رونویسی",
                    "model": "dorna-8b-q4_k_m",
                    "operation": "correction",
                    "style": "formal",
                }
            ]
        }
    )

    text: str = Field(
        min_length=1, max_length=12000, description="Persian source text to process."
    )
    model: str | None = Field(
        default=None,
        min_length=1,
        description="Legacy single installed Dorna model identifier.",
    )
    models: list[str] | None = Field(
        default=None,
        min_length=1,
        description="Ordered installed Dorna model identifiers.",
    )
    operation: str = Field(
        default="correction",
        description="Processing workflow. Supported values are `correction` and `minutes`.",
    )
    style: str = Field(
        default="formal",
        description="Writing style. Supported values are `formal`, `semi_formal`, and `action`.",
    )

    @model_validator(mode="after")
    def exactly_one_model_field(self):
        if (self.model is None) == (self.models is None):
            raise ValueError("Specify exactly one of model or models")
        return self


class ProxyConfigRequest(BaseModel):
    """JSON body used to replace the download proxy configuration."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"enabled": True, "uri": "socks5h://user:password@proxy.example:1080"}
            ]
        }
    )

    enabled: bool = Field(
        default=False, description="Whether model downloads must use this proxy."
    )
    uri: str = Field(
        default="",
        max_length=2048,
        description="HTTP(S) or SOCKS5(H) proxy URI. Credentials are accepted but never returned verbatim.",
    )


class CustomModelFileRequest(BaseModel):
    """One downloadable artifact in an administrator-defined model bundle."""

    filename: str = Field(min_length=1, max_length=512)
    download_url: HttpUrl
    expected_size: int | None = Field(default=None, gt=0)
    sha256: str | None = None

    @field_validator("filename")
    @classmethod
    def valid_filename(cls, value):
        parts = value.replace("\\", "/").split("/")
        if value.startswith("/") or "\\" in value or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("filename must be a safe relative path")
        return value

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value):
        if value is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("sha256 must contain exactly 64 hexadecimal characters")
        return value.lower() if value else None

    @field_validator("download_url")
    @classmethod
    def public_https_download(cls, value):
        rendered = str(value)
        if not rendered.startswith("https://") or "@" in rendered.split("//", 1)[1].split("/", 1)[0]:
            raise ValueError("download_url must be credential-free HTTPS")
        host = value.host
        if host in {"localhost", "localhost.localdomain"}:
            raise ValueError("download_url must not target localhost")
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError("download_url must not target a non-public IP address")
        except ValueError as error:
            if "non-public" in str(error):
                raise
        return value


class CustomTextModelRequest(BaseModel):
    """Administrator-defined GGUF or faster-whisper model bundle."""

    id: str = Field(min_length=1, max_length=80, description="Stable model id exposed through the API.")
    display_name: str = Field(min_length=1, max_length=160)
    kind: Literal["llm", "asr", "decision"] = "llm"
    description: str = Field(default="", max_length=2000)
    download_url: HttpUrl | None = None
    filename: str | None = Field(default=None, max_length=255, description="Local GGUF filename.")
    files: list[CustomModelFileRequest] | None = None
    repository_url: HttpUrl | None = None
    expected_size: int | None = Field(default=None, gt=0)
    sha256: str | None = Field(default=None, description="Recommended lowercase SHA-256 checksum.")
    revision: str | None = Field(default=None, max_length=200)
    license: str | None = Field(default=None, max_length=100)
    context_size: int | None = Field(default=None, ge=512, le=1048576)
    engine: Literal["gliner2_5_multi_decide", "laya_multilingual"] | None = None
    source_type: Literal["direct", "huggingface"] = "direct"
    hf_repository: str | None = Field(default=None, max_length=200)
    hf_subfolder: str | None = Field(default=None, max_length=200)
    max_concurrent: int | None = Field(default=None, ge=1, le=32)
    cpu_threads: int | None = Field(default=None, ge=1, le=128)
    confidence_threshold: float | None = Field(default=None, ge=0, le=1)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", value):
            raise ValueError("id may contain only letters, digits, dot, underscore, and hyphen")
        return value

    @field_validator("filename")
    @classmethod
    def valid_filename(cls, value):
        if value is not None and ("/" in value or "\\" in value or value in {".", ".."} or not value.lower().endswith(".gguf")):
            raise ValueError("filename must be a plain .gguf filename")
        return value

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value):
        if value is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("sha256 must contain exactly 64 hexadecimal characters")
        return value.lower() if value else None

    @model_validator(mode="after")
    def valid_bundle(self):
        if self.kind == "llm":
            if self.files:
                raise ValueError("LLM models use one GGUF file; do not provide files")
            if not self.download_url or not self.filename:
                raise ValueError("LLM models require download_url and filename")
            return self
        if self.kind == "decision":
            if self.engine is None:
                raise ValueError("decision models require an engine")
            if self.source_type == "huggingface":
                if not self.hf_repository or not self.revision or len(self.revision) != 40 or not re.fullmatch(r"[0-9a-fA-F]{40}", self.revision):
                    raise ValueError("Hugging Face decision models require a pinned 40-character commit revision")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*", self.hf_repository):
                    raise ValueError("hf_repository must be a public owner/repository identifier")
                if self.download_url or self.filename or self.files:
                    raise ValueError("Hugging Face decision models do not accept direct files")
            else:
                if not self.files or any(item.sha256 is None for item in self.files):
                    raise ValueError("direct decision model files require SHA-256 values")
            return self
        if self.download_url or self.filename:
            raise ValueError("ASR models require the faster-whisper files list, not a single file")
        required = {"model.bin", "config.json", "tokenizer.json", "vocabulary.json", "preprocessor_config.json"}
        supplied = {item.filename for item in self.files or []}
        if len(supplied) != len(self.files or []) or supplied != required:
            raise ValueError("faster-whisper requires exactly model.bin, config.json, tokenizer.json, vocabulary.json, and preprocessor_config.json")
        return self


class DecisionQuestionRequest(BaseModel):
    """A typed decision question with criteria that match its decision primitive."""

    type: Literal["choice", "multi_label", "score", "noul"]
    instructions: str = Field(min_length=1, max_length=2000)
    criteria: dict[str, str] | list[str] | None = None

    @model_validator(mode="after")
    def validate_criteria(self):
        if self.type in {"choice", "multi_label"}:
            if not isinstance(self.criteria, dict) or len(self.criteria) < 2:
                raise ValueError(f"{self.type} requires at least two named criteria")
        elif self.type == "score":
            if not isinstance(self.criteria, list) or not 2 <= len(self.criteria) <= 10:
                raise ValueError("score requires two to ten ordered criteria levels")
        elif self.criteria is not None and not isinstance(self.criteria, dict):
            raise ValueError("noul criteria must be omitted or provide true/false descriptions")
        return self


class DecisionRequest(BaseModel):
    model: str = Field(min_length=1, max_length=80)
    state: str | dict[str, Any] = Field(description="Text or a JSON object rendered deterministically for the decision engine.")
    questions: dict[str, DecisionQuestionRequest] = Field(min_length=1, max_length=32)
    confidence_threshold: float | None = Field(default=None, ge=0, le=1)

    @field_validator("state")
    @classmethod
    def valid_state(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("state must not be empty")
        return value
