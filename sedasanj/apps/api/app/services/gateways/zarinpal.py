"""ZarinPal v4 (https://www.zarinpal.com/docs/paymentGateway/)."""

from __future__ import annotations

from typing import Any

from app.services.gateways.base import (
    AttemptRef,
    CallbackInfo,
    Gateway,
    GatewayError,
    PaymentContext,
    PaymentStart,
    RedirectSpec,
    Verification,
    valid_email,
    valid_mobile,
)

ERRORS = {
    "-9": "validation error (amount limits, callback or description)",
    "-10": "merchant id or server IP is not registered",
    "-11": "terminal is inactive",
    "-12": "too many attempts, retry later",
    "-14": "callback domain differs from the registered domain",
    "-15": "terminal is suspended",
    "-16": "merchant level is below silver",
    "-41": "amount is above the maximum",
    "-50": "paid amount differs from the requested amount",
    "-51": "payment session was not successful",
    "-53": "payment belongs to another merchant",
    "-54": "invalid authority",
    "-55": "transaction not found",
}


class ZarinpalGateway(Gateway):
    code = "zarinpal"
    label = "زرین‌پال"
    min_rial = 10_000
    max_rial = 1_000_000_000
    supports_reverse = True

    @property
    def _api(self) -> str:
        return "https://sandbox.zarinpal.com" if self.sandbox else "https://payment.zarinpal.com"

    @staticmethod
    def _data(body: dict[str, Any]) -> dict[str, Any]:
        data = body.get("data")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _error_code(body: dict[str, Any]) -> str:
        errors = body.get("errors")
        if isinstance(errors, dict) and errors.get("code") is not None:
            return str(errors["code"])
        return "unknown"

    async def request(self, ctx: PaymentContext) -> PaymentStart:
        metadata: dict[str, str] = {"order_id": ctx.order_number}
        if valid_mobile(ctx.mobile):
            metadata["mobile"] = ctx.mobile
        if valid_email(ctx.email):
            metadata["email"] = ctx.email
        body = await self.post_json(
            f"{self._api}/pg/v4/payment/request.json",
            {
                "merchant_id": self.credentials["merchant_id"],
                "amount": ctx.amount_rial,
                "currency": "IRR",
                "description": ctx.description,
                "callback_url": ctx.callback_url,
                "metadata": metadata,
            },
        )
        data = self._data(body)
        authority = data.get("authority")
        if data.get("code") != 100 or not authority:
            code = self._error_code(body)
            raise GatewayError(code, ERRORS.get(code, "payment request was rejected"))
        return PaymentStart(
            str(authority),
            RedirectSpec("GET", f"{self._api}/pg/StartPay/{authority}"),
            body,
        )

    def parse_callback(self, params: dict[str, str]) -> CallbackInfo:
        authority = params.get("Authority") or None
        if params.get("Status", "").upper() == "OK" and authority:
            return CallbackInfo("ok", authority, None, None, None)
        return CallbackInfo("canceled", authority, None, None, "NOK")

    async def verify(self, attempt: AttemptRef) -> Verification:
        body = await self.post_json(
            f"{self._api}/pg/v4/payment/verify.json",
            {
                "merchant_id": self.credentials["merchant_id"],
                "amount": attempt.amount_rial,
                "authority": attempt.authority,
            },
        )
        data = self._data(body)
        code = data.get("code")
        if code in (100, 101):
            ref = data.get("ref_id")
            return Verification(
                True,
                code=str(code),
                ref_id=str(ref) if ref is not None else None,
                card_pan=str(data["card_pan"]) if data.get("card_pan") else None,
                amount_rial=attempt.amount_rial,
                already_verified=code == 101,
                response=body,
            )
        return Verification(False, code=str(code or self._error_code(body)), response=body)

    async def inquiry(self, attempt: AttemptRef) -> Verification:
        body = await self.post_json(
            f"{self._api}/pg/v4/payment/inquiry.json",
            {"merchant_id": self.credentials["merchant_id"], "authority": attempt.authority},
        )
        data = self._data(body)
        status = str(data.get("status") or "")
        # PAID = paid but not verified; VERIFIED = already verified.  Both need the verify call.
        return Verification(status in {"PAID", "VERIFIED"}, code=status or None, response=body)

    async def reverse(self, attempt: AttemptRef) -> bool:
        body = await self.post_json(
            f"{self._api}/pg/v4/payment/reverse.json",
            {"merchant_id": self.credentials["merchant_id"], "authority": attempt.authority},
        )
        return self._data(body).get("code") == 100
