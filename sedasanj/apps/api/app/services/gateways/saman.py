"""Saman Electronic Payment (SEP) IPG, token based (`onlinepg`).

Endpoints and fields follow the reference drivers of shetabit/multipay and dizatech/saman_ipg.
⚠ needs lab confirmation: the reverse response fields and the reversal window.
"""

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
)

TOKEN_URL = "https://sep.shaparak.ir/onlinepg/onlinepg"
PAY_URL = "https://sep.shaparak.ir/OnlinePG/OnlinePG"
VERIFY_URL = "https://sep.shaparak.ir/verifyTxnRandomSessionkey/ipg/VerifyTransaction"
REVERSE_URL = "https://sep.shaparak.ir/verifyTxnRandomSessionkey/ipg/ReverseTransaction"

TOKEN_ERRORS = {
    "-1": "invalid terminal or request",
    "1": "canceled by the buyer",
    "3": "payment was not completed",
    "4": "the buyer did not respond in time",
    "5": "invalid parameters",
    "8": "server IP is not registered with the bank",
    "10": "token not found",
    "11": "terminal accepts only token payments",
    "12": "terminal not found",
}


class SamanGateway(Gateway):
    code = "saman"
    label = "سپ (بانک سامان)"
    min_rial = 10_000
    supports_reverse = True

    @property
    def _terminal(self) -> str:
        return self.credentials["terminal_id"]

    async def request(self, ctx: PaymentContext) -> PaymentStart:
        body = await self.post_json(
            TOKEN_URL,
            {
                "action": "token",
                "TerminalId": self._terminal,
                "Amount": ctx.amount_rial,
                "ResNum": str(ctx.order_ref),
                "RedirectUrl": ctx.callback_url,
                "CellNumber": ctx.mobile,
            },
        )
        token = body.get("token")
        if body.get("status") != 1 or not token:
            code = str(body.get("errorCode", "unknown"))
            raise GatewayError(code, TOKEN_ERRORS.get(code, "payment request was rejected"))
        return PaymentStart(
            str(token),
            RedirectSpec("POST", PAY_URL, {"Token": str(token), "GetMethod": "false"}),
            {k: v for k, v in body.items() if k != "token"},
        )

    def parse_callback(self, params: dict[str, str]) -> CallbackInfo:
        ref_num = params.get("RefNum", "")
        res_num = params.get("ResNum", "")
        order_ref = int(res_num) if res_num.isdigit() else None
        reference = {
            k: params[k]
            for k in ("RefNum", "RRN", "TraceNo", "SecurePan", "State")
            if params.get(k)
        }
        success = params.get("Status") == "2" or params.get("State", "").upper() == "OK"
        if success and ref_num:
            return CallbackInfo("ok", params.get("Token") or None, order_ref, None, None, reference)
        state = params.get("State", "")
        canceled = "cancel" in state.lower() or params.get("Status") == "1"
        return CallbackInfo(
            "canceled" if canceled else "failed",
            params.get("Token") or None,
            order_ref,
            None,
            params.get("Status") or state or "unknown",
            reference,
        )

    async def verify(self, attempt: AttemptRef) -> Verification:
        ref_num = attempt.callback.get("RefNum")
        if not ref_num:
            return Verification(False, code="no_ref_num")
        body = await self.post_json(
            VERIFY_URL, {"RefNum": ref_num, "TerminalNumber": int(self._terminal)}
        )
        detail = body.get("TransactionDetail")
        detail = detail if isinstance(detail, dict) else {}
        code = body.get("ResultCode")
        amount = detail.get("AffectiveAmount", detail.get("OrginalAmount"))
        matches = str(detail.get("RefNum", ref_num)) == str(ref_num)
        # ResultCode 2 with a matching detail is a repeated verify of the same transaction.
        if code in (0, 2) and detail and matches:
            return Verification(
                True,
                code=str(code),
                ref_id=ref_num,
                rrn=str(detail["RRN"]) if detail.get("RRN") else None,
                card_pan=str(detail["MaskedPan"]) if detail.get("MaskedPan") else None,
                amount_rial=int(str(amount)) if str(amount).isdigit() else None,
                already_verified=code == 2,
                response=body,
            )
        return Verification(False, code=str(code), response=body)

    async def reverse(self, attempt: AttemptRef) -> bool:
        ref_num = attempt.callback.get("RefNum")
        if not ref_num:
            raise GatewayError("no_ref_num", "the bank reference number is missing")
        body: dict[str, Any] = await self.post_json(
            REVERSE_URL, {"RefNum": ref_num, "TerminalNumber": int(self._terminal)}
        )
        return body.get("ResultCode") == 0
