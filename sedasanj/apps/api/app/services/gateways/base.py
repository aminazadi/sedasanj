"""Shared contract for Iranian payment-gateway adapters.

Every adapter works in rial and never touches the database; `app.services.payments` owns
orders, attempts and the ledger.  Adapters raise `GatewayError` only for transport problems or
rejected requests; an unpaid or canceled payment is a normal `Verification(success=False)`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx


class GatewayError(Exception):
    """A gateway call failed.  `retryable` means the outcome is unknown (timeout, 5xx)."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class RedirectSpec:
    """How the browser must reach the bank: a GET link or an auto-submitted POST form."""

    method: Literal["GET", "POST"]
    url: str
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentContext:
    amount_rial: int
    order_ref: int
    order_number: str
    description: str
    callback_url: str
    mobile: str
    email: str


@dataclass(frozen=True)
class PaymentStart:
    token: str
    redirect: RedirectSpec
    response: dict[str, Any]


@dataclass(frozen=True)
class AttemptRef:
    """What the adapter needs to know about a stored attempt."""

    authority: str
    order_ref: int
    amount_rial: int
    callback: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CallbackInfo:
    outcome: Literal["ok", "canceled", "failed"]
    token: str | None
    order_ref: int | None
    amount_rial: int | None
    failure_code: str | None
    reference: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Verification:
    success: bool
    code: str | None = None
    ref_id: str | None = None
    rrn: str | None = None
    card_pan: str | None = None
    amount_rial: int | None = None
    already_verified: bool = False
    response: dict[str, Any] = field(default_factory=dict)


class Gateway(ABC):
    code: str
    label: str
    min_rial: int = 10_000
    max_rial: int | None = None
    supports_reverse: bool = False
    needs_settle: bool = False

    def __init__(
        self,
        credentials: dict[str, str],
        *,
        sandbox: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.credentials = credentials
        self.sandbox = sandbox
        self._transport = transport

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=20.0, follow_redirects=False, transport=self._transport)

    async def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self.client() as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise GatewayError("network", "payment gateway is unreachable", retryable=True) from exc
        if response.status_code >= 500:
            raise GatewayError("http_5xx", "payment gateway is unavailable", retryable=True)
        try:
            body = response.json()
        except ValueError as exc:
            raise GatewayError(
                f"http_{response.status_code}",
                "invalid response from payment gateway",
                retryable=response.status_code >= 500,
            ) from exc
        if not isinstance(body, dict):
            raise GatewayError("bad_body", "invalid response from payment gateway")
        return body

    @abstractmethod
    async def request(self, ctx: PaymentContext) -> PaymentStart: ...

    @abstractmethod
    def parse_callback(self, params: dict[str, str]) -> CallbackInfo: ...

    @abstractmethod
    async def verify(self, attempt: AttemptRef) -> Verification: ...

    async def inquiry(self, attempt: AttemptRef) -> Verification:
        """Read-only status check; default re-runs the idempotent verify."""
        return await self.verify(attempt)

    async def settle(self, attempt: AttemptRef) -> bool:
        return True

    async def reverse(self, attempt: AttemptRef) -> bool:
        raise GatewayError("unsupported", "this gateway does not support reversal")
