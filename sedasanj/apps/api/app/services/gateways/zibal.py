"""Zibal IPG (https://help.zibal.ir).  Amounts are rial; merchant `zibal` is the sandbox."""

from __future__ import annotations

from typing import Any, Literal

from app.services.gateways.base import (
    AttemptRef,
    CallbackInfo,
    Gateway,
    GatewayError,
    PaymentContext,
    PaymentStart,
    RedirectSpec,
    Verification,
    valid_mobile,
)

API = "https://gateway.zibal.ir"
REQUEST_ERRORS = {
    102: "merchant not found",
    103: "merchant is inactive",
    104: "merchant is invalid",
    105: "amount must be at least 1,000 rial",
    106: "callback URL is invalid",
    113: "amount exceeds the terminal limit",
}


class ZibalGateway(Gateway):
    code = "zibal"
    label = "زیبال"
    min_rial = 10_000
    max_rial = None

    @property
    def _merchant(self) -> str:
        return "zibal" if self.sandbox else self.credentials["merchant_id"]

    async def request(self, ctx: PaymentContext) -> PaymentStart:
        payload: dict[str, Any] = {
            "merchant": self._merchant,
            "amount": ctx.amount_rial,
            "callbackUrl": ctx.callback_url,
            "description": ctx.description,
            "orderId": str(ctx.order_ref),
        }
        if valid_mobile(ctx.mobile):
            payload["mobile"] = ctx.mobile
        body = await self.post_json(f"{API}/v1/request", payload)
        result = body.get("result")
        track_id = body.get("trackId")
        if result != 100 or not track_id:
            code = str(result)
            raise GatewayError(
                code,
                REQUEST_ERRORS.get(
                    result if isinstance(result, int) else 0, "payment request was rejected"
                ),
            )
        return PaymentStart(str(track_id), RedirectSpec("GET", f"{API}/start/{track_id}"), body)

    def parse_callback(self, params: dict[str, str]) -> CallbackInfo:
        track = params.get("trackId") or None
        order = params.get("orderId", "")
        order_ref = int(order) if order.isdigit() else None
        reference: dict[str, str] = {k: params[k] for k in ("status", "success") if k in params}
        if params.get("success") == "1":
            return CallbackInfo("ok", track, order_ref, None, None, reference)
        outcome: Literal["canceled", "failed"] = (
            "canceled" if params.get("status") == "3" else "failed"
        )
        return CallbackInfo(outcome, track, order_ref, None, params.get("status") or "0", reference)

    async def verify(self, attempt: AttemptRef) -> Verification:
        body = await self.post_json(
            f"{API}/v1/verify",
            {"merchant": self._merchant, "trackId": int(attempt.authority)},
        )
        result = body.get("result")
        if result in (100, 201):
            amount = body.get("amount")
            return Verification(
                True,
                code=str(result),
                ref_id=str(body["refNumber"]) if body.get("refNumber") is not None else None,
                card_pan=str(body["cardNumber"]) if body.get("cardNumber") else None,
                amount_rial=int(amount) if isinstance(amount, int) else None,
                already_verified=result == 201,
                response=body,
            )
        return Verification(False, code=str(result), response=body)

    async def inquiry(self, attempt: AttemptRef) -> Verification:
        # ⚠ needs lab confirmation: /v1/inquiry fields; status 1/2 means paid.
        body = await self.post_json(
            f"{API}/v1/inquiry",
            {"merchant": self._merchant, "trackId": int(attempt.authority)},
        )
        paid = body.get("result") == 100 and body.get("status") in (1, 2)
        return Verification(paid, code=str(body.get("status")), response=body)
