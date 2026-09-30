from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from app.errors import ApiError

ALLOWED_SCHEMES = ("http", "https")
BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata", "metadata.google.internal"})


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def assert_safe_webhook_url(raw_url: str) -> None:
    """§12: a tenant-supplied callback must never reach the platform's own network."""
    parsed = urlparse(raw_url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ApiError("invalid_request", "webhook url must use http or https")
    host = parsed.hostname
    if not host:
        raise ApiError("invalid_request", "webhook url must contain a hostname")
    if host.lower() in BLOCKED_HOSTNAMES or host.lower().endswith(".local"):
        raise ApiError("invalid_request", "webhook url may not point at the local network")

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ApiError("invalid_request", f"webhook host does not resolve: {host}") from exc

    addresses = {str(info[4][0]) for info in infos}
    if not addresses or not all(_is_public(address) for address in addresses):
        raise ApiError("invalid_request", "webhook url resolves to a non-public address")


async def assert_safe_webhook_url_async(raw_url: str) -> None:
    """Same checks off the event loop, since name resolution blocks."""
    await asyncio.to_thread(assert_safe_webhook_url, raw_url)
