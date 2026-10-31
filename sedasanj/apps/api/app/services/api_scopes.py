"""Scopes a tenant API key may carry. There is deliberately no assistant scope."""

from __future__ import annotations

from ipaddress import ip_address, ip_network

API_KEY_SCOPES: tuple[str, ...] = (
    "ingest:write",
    "crm:write",
    "module:sync",
    "calls:read",
    "contacts:read",
)
DEFAULT_NEW_KEY_SCOPES: tuple[str, ...] = ("ingest:write", "module:sync")
MAX_ALLOWED_CIDRS = 20


def normalize_cidrs(values: list[str]) -> list[str]:
    """Return canonical CIDR strings; a bare address becomes a /32 or /128."""
    result: list[str] = []
    for raw in values:
        network = ip_network(raw.strip(), strict=False)
        canonical = str(network)
        if canonical not in result:
            result.append(canonical)
    return result


def ip_allowed(allowed_cidrs: list[str], client_ip: str | None) -> bool:
    """An empty allowlist means any source address."""
    if not allowed_cidrs:
        return True
    if not client_ip:
        return False
    try:
        address = ip_address(client_ip)
    except ValueError:
        return False
    return any(address in ip_network(cidr, strict=False) for cidr in allowed_cidrs)
