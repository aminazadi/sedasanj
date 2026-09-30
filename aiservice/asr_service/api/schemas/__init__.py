"""Typed request and response contracts exposed through OpenAPI."""

from .requests import ProxyConfigRequest, TextProcessRequest
from .responses import *  # noqa: F401,F403 - schema package public surface

__all__ = ["ProxyConfigRequest", "TextProcessRequest"]
