"""Behpardakht Mellat (PGW) over SOAP.

Flow: bpPayRequest → browser POST `RefId` → callback → bpVerifyRequest → bpSettleRequest.
Verified against the shetabit/multipay and dizatech/behpardakht_ipg drivers.
⚠ needs lab confirmation: SOAP namespace `http://interfaces.core.sw.bps.com/` and the
bpInquiryRequest / bpReversalRequest parameter names.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree
from xml.sax.saxutils import escape

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

SOAP_URL = "https://bpm.shaparak.ir/pgwchannel/services/pgw"
PAY_URL = "https://bpm.shaparak.ir/pgwchannel/startpay.mellat"
NAMESPACE = "http://interfaces.core.sw.bps.com/"
TEHRAN = timezone(timedelta(hours=3, minutes=30))

CODES = {
    "11": "invalid card number",
    "12": "insufficient balance",
    "13": "wrong card PIN",
    "17": "canceled by the buyer",
    "21": "invalid merchant",
    "24": "merchant credentials are invalid",
    "25": "invalid amount",
    "41": "duplicate order id",
    "421": "server IP is not registered with the bank",
    "62": "callback domain differs from the registered domain",
}
_RETURN = re.compile(r"<(?:\w+:)?return>\s*([^<]*?)\s*</(?:\w+:)?return>")


class BehpardakhtGateway(Gateway):
    code = "behpardakht"
    label = "به‌پرداخت ملت"
    min_rial = 10_000
    supports_reverse = True
    needs_settle = True

    def _envelope(self, operation: str, fields: dict[str, str | int]) -> str:
        auth = {
            "terminalId": self.credentials["terminal_id"],
            "userName": self.credentials["username"],
            "userPassword": self.credentials["password"],
        }
        body = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in {**auth, **fields}.items())
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            f'xmlns:int="{NAMESPACE}"><soapenv:Body><int:{operation}>{body}'
            f"</int:{operation}></soapenv:Body></soapenv:Envelope>"
        )

    async def call(self, operation: str, fields: dict[str, str | int]) -> str:
        """Returns the SOAP `return` value; never logs the envelope (it holds the password)."""
        try:
            async with self.client() as client:
                response = await client.post(
                    SOAP_URL,
                    content=self._envelope(operation, fields).encode("utf-8"),
                    headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
                )
        except Exception as exc:  # noqa: BLE001 - transport errors are all "unknown outcome"
            raise GatewayError("network", "payment gateway is unreachable", retryable=True) from exc
        if response.status_code >= 500:
            raise GatewayError("http_5xx", "payment gateway is unavailable", retryable=True)
        return self.parse_return(response.text)

    @staticmethod
    def parse_return(xml: str) -> str:
        if "<!DOCTYPE" in xml or "<!ENTITY" in xml:
            raise GatewayError("bad_body", "invalid response from payment gateway")
        try:
            ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            raise GatewayError("bad_body", "invalid response from payment gateway") from exc
        match = _RETURN.search(xml)
        if match is None:
            raise GatewayError("bad_body", "invalid response from payment gateway")
        return match.group(1)

    def _sale_fields(self, attempt: AttemptRef) -> dict[str, str | int]:
        return {
            "orderId": attempt.order_ref,
            "saleOrderId": attempt.order_ref,
            "saleReferenceId": attempt.callback.get("SaleReferenceId", ""),
        }

    async def request(self, ctx: PaymentContext) -> PaymentStart:
        now = datetime.now(TEHRAN)
        result = await self.call(
            "bpPayRequest",
            {
                "orderId": ctx.order_ref,
                "amount": ctx.amount_rial,
                "localDate": now.strftime("%Y%m%d"),
                "localTime": now.strftime("%H%M%S"),
                "additionalData": ctx.order_number,
                "callBackUrl": ctx.callback_url,
                "payerId": 0,
            },
        )
        code, _, ref_id = result.partition(",")
        if code != "0" or not ref_id:
            raise GatewayError(code or "unknown", CODES.get(code, "payment request was rejected"))
        fields = {"RefId": ref_id}
        if valid_mobile(ctx.mobile):
            fields["MobileNo"] = ctx.mobile
        return PaymentStart(ref_id, RedirectSpec("POST", PAY_URL, fields), {"return_code": code})

    def parse_callback(self, params: dict[str, str]) -> CallbackInfo:
        order = params.get("SaleOrderId", "")
        order_ref = int(order) if order.isdigit() else None
        final = params.get("FinalAmount", "")
        amount = int(final) if final.isdigit() else None
        reference = {
            k: params[k]
            for k in ("SaleReferenceId", "CardHolderPan", "FinalAmount")
            if params.get(k)
        }
        res = params.get("ResCode", "")
        token = params.get("RefId") or None
        if res == "0" and params.get("SaleReferenceId"):
            return CallbackInfo("ok", token, order_ref, amount, None, reference)
        return CallbackInfo(
            "canceled" if res == "17" else "failed",
            token,
            order_ref,
            amount,
            res or "unknown",
            reference,
        )

    async def verify(self, attempt: AttemptRef) -> Verification:
        code = await self.call("bpVerifyRequest", self._sale_fields(attempt))
        if code in {"0", "43", "45"}:  # 45: already settled, so verified earlier
            return Verification(
                True,
                code=code,
                ref_id=attempt.callback.get("SaleReferenceId"),
                card_pan=attempt.callback.get("CardHolderPan"),
                amount_rial=int(attempt.callback["FinalAmount"])
                if attempt.callback.get("FinalAmount", "").isdigit()
                else None,
                already_verified=code != "0",
                response={"return_code": code},
            )
        return Verification(False, code=code, response={"return_code": code})

    async def inquiry(self, attempt: AttemptRef) -> Verification:
        if not attempt.callback.get("SaleReferenceId"):
            return Verification(False, code="no_sale_reference")
        code = await self.call("bpInquiryRequest", self._sale_fields(attempt))
        return Verification(code == "0", code=code, response={"return_code": code})

    async def settle(self, attempt: AttemptRef) -> bool:
        code = await self.call("bpSettleRequest", self._sale_fields(attempt))
        return code in {"0", "45"}

    async def reverse(self, attempt: AttemptRef) -> bool:
        code = await self.call("bpReversalRequest", self._sale_fields(attempt))
        return code in {"0", "48"}
