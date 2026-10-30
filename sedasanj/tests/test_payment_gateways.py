from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from app.errors import ERROR_STATUS
from app.services.gateways import AttemptRef, GatewayError, PaymentContext
from app.services.gateways.behpardakht import BehpardakhtGateway
from app.services.gateways.registry import GATEWAY_ORDER, GATEWAYS, build_gateway
from app.services.gateways.saman import SamanGateway
from app.services.gateways.zarinpal import ZarinpalGateway
from app.services.gateways.zibal import ZibalGateway
from app.services.payments import new_order_ref

Handler = Callable[[httpx.Request], httpx.Response]


def transport(handler: Handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def context(**overrides: object) -> PaymentContext:
    values: dict[str, object] = {
        "amount_rial": 500_000,
        "order_ref": 1234567890123,
        "order_number": "CR-1",
        "description": "credit",
        "callback_url": "https://app.example/v1/payments/x/callback?token=t",
        "mobile": "09123456789",
        "email": "a@example.com",
    }
    values.update(overrides)
    return PaymentContext(**values)  # type: ignore[arg-type]


def test_registry_has_four_gateways_and_labels() -> None:
    assert set(GATEWAY_ORDER) == set(GATEWAYS) == {"zarinpal", "zibal", "saman", "behpardakht"}
    assert all(cls.label for cls in GATEWAYS.values())


def test_new_order_ref_is_numeric_and_unique() -> None:
    refs = {new_order_ref() for _ in range(2000)}
    assert len(refs) == 2000
    assert all(0 < ref < 2**63 for ref in refs)


def test_new_api_error_codes_map() -> None:
    assert ERROR_STATUS["payment_gateway_unavailable"] == 502
    assert ERROR_STATUS["payment_method_unavailable"] == 409


# ---- ZarinPal -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zarinpal_request_verify_and_amount() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("request.json"):
            return httpx.Response(200, json={"data": {"code": 100, "authority": "A0001"}})
        return httpx.Response(
            200, json={"data": {"code": 100, "ref_id": 77, "card_pan": "6037****1234"}}
        )

    gw = ZarinpalGateway({"merchant_id": "m" * 36}, transport=transport(handler))
    started = await gw.request(context())
    assert started.token == "A0001"
    assert started.redirect.method == "GET"
    assert started.redirect.url == "https://payment.zarinpal.com/pg/StartPay/A0001"
    body = json.loads(seen[0].content)
    assert body["amount"] == 500_000 and body["currency"] == "IRR"
    verified = await gw.verify(AttemptRef("A0001", 1, 500_000))
    assert verified.success and verified.ref_id == "77" and verified.amount_rial == 500_000
    assert json.loads(seen[1].content)["amount"] == 500_000


@pytest.mark.asyncio
async def test_zarinpal_already_verified_and_failure_codes() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"code": 101, "ref_id": 5}})

    gw = ZarinpalGateway({"merchant_id": "m" * 36}, transport=transport(ok))
    result = await gw.verify(AttemptRef("A1", 1, 10_000))
    assert result.success and result.already_verified

    def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "errors": {"code": -10, "message": "ip"}})

    gw = ZarinpalGateway({"merchant_id": "m" * 36}, transport=transport(rejected))
    with pytest.raises(GatewayError) as err:
        await gw.request(context())
    assert err.value.code == "-10" and "IP" in err.value.message


def test_zarinpal_callback_parsing_and_sandbox_host() -> None:
    gw = ZarinpalGateway({"merchant_id": "m"}, sandbox=True)
    assert gw.parse_callback({"Authority": "A1", "Status": "OK"}).outcome == "ok"
    assert gw.parse_callback({"Authority": "A1", "Status": "NOK"}).outcome == "canceled"
    assert gw._api == "https://sandbox.zarinpal.com"


@pytest.mark.asyncio
async def test_zarinpal_inquiry_does_not_verify() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"data": {"status": "PAID", "code": 100}})

    gw = ZarinpalGateway({"merchant_id": "m"}, transport=transport(handler))
    assert (await gw.inquiry(AttemptRef("A1", 1, 10_000))).success
    assert calls == ["/pg/v4/payment/inquiry.json"]


# ---- Zibal ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zibal_flow_and_sandbox_merchant() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if request.url.path == "/v1/request":
            return httpx.Response(200, json={"result": 100, "trackId": 9988})
        return httpx.Response(
            200,
            json={"result": 100, "amount": 500_000, "refNumber": 42, "cardNumber": "6037****99"},
        )

    gw = ZibalGateway({"merchant_id": "real"}, sandbox=True, transport=transport(handler))
    started = await gw.request(context())
    assert started.token == "9988"
    assert started.redirect.url == "https://gateway.zibal.ir/start/9988"
    assert bodies[0]["merchant"] == "zibal" and bodies[0]["orderId"] == "1234567890123"
    verified = await gw.verify(AttemptRef("9988", 1, 500_000))
    assert verified.success and verified.amount_rial == 500_000 and verified.ref_id == "42"


@pytest.mark.asyncio
async def test_zibal_verify_unpaid_and_duplicate() -> None:
    def unpaid(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": 202})

    gw = ZibalGateway({"merchant_id": "m"}, transport=transport(unpaid))
    assert not (await gw.verify(AttemptRef("1", 1, 10_000))).success

    def dup(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": 201, "amount": 10_000})

    gw = ZibalGateway({"merchant_id": "m"}, transport=transport(dup))
    result = await gw.verify(AttemptRef("1", 1, 10_000))
    assert result.success and result.already_verified


def test_zibal_callback() -> None:
    gw = ZibalGateway({"merchant_id": "m"})
    ok = gw.parse_callback({"success": "1", "status": "2", "trackId": "9", "orderId": "55"})
    assert ok.outcome == "ok" and ok.token == "9" and ok.order_ref == 55
    assert gw.parse_callback({"success": "0", "status": "3", "trackId": "9"}).outcome == "canceled"
    assert gw.parse_callback({"success": "0", "status": "4"}).outcome == "failed"


# ---- Saman ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_saman_token_and_verify() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if "onlinepg" in request.url.path.lower():
            return httpx.Response(200, json={"status": 1, "token": "TKN"})
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "Success": True,
                "TransactionDetail": {
                    "RefNum": "R1",
                    "RRN": "99",
                    "MaskedPan": "6219****1111",
                    "AffectiveAmount": 500_000,
                },
            },
        )

    gw = SamanGateway({"terminal_id": "1234"}, transport=transport(handler))
    started = await gw.request(context())
    assert started.token == "TKN"
    assert started.redirect.method == "POST" and started.redirect.fields["Token"] == "TKN"
    assert bodies[0]["action"] == "token" and bodies[0]["ResNum"] == "1234567890123"
    verified = await gw.verify(AttemptRef("TKN", 1, 500_000, {"RefNum": "R1"}))
    assert verified.success and verified.rrn == "99" and verified.amount_rial == 500_000
    assert bodies[1] == {"RefNum": "R1", "TerminalNumber": 1234}


@pytest.mark.asyncio
async def test_saman_verify_without_ref_and_error() -> None:
    gw = SamanGateway({"terminal_id": "1234"})
    assert (await gw.verify(AttemptRef("T", 1, 10_000))).code == "no_ref_num"

    def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": -1, "errorCode": "8", "errorDesc": "ip"})

    gw = SamanGateway({"terminal_id": "1234"}, transport=transport(rejected))
    with pytest.raises(GatewayError) as err:
        await gw.request(context())
    assert err.value.code == "8" and "IP" in err.value.message


def test_saman_callback() -> None:
    gw = SamanGateway({"terminal_id": "1"})
    ok = gw.parse_callback({"Status": "2", "RefNum": "R1", "ResNum": "77", "RRN": "5"})
    assert ok.outcome == "ok" and ok.order_ref == 77 and ok.reference["RefNum"] == "R1"
    # A success status without a bank reference must never be trusted.
    assert gw.parse_callback({"Status": "2", "ResNum": "77"}).outcome == "failed"
    assert gw.parse_callback({"State": "Canceled By User", "Status": "1"}).outcome == "canceled"


# ---- Behpardakht ----------------------------------------------------------------------------


def soap(value: str) -> str:
    return (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
        f'<ns1:resp xmlns:ns1="http://interfaces.core.sw.bps.com/"><return>{value}</return>'
        "</ns1:resp></soap:Body></soap:Envelope>"
    )


CREDS = {"terminal_id": "555", "username": "user", "password": "p&ss<word>"}


@pytest.mark.asyncio
async def test_behpardakht_pay_request_escapes_and_redirects() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content.decode())
        return httpx.Response(200, text=soap("0,REFID123"))

    gw = BehpardakhtGateway(CREDS, transport=transport(handler))
    started = await gw.request(context())
    assert started.token == "REFID123"
    assert started.redirect.method == "POST"
    assert started.redirect.fields["RefId"] == "REFID123"
    assert "p&amp;ss&lt;word&gt;" in sent[0]
    assert "<orderId>1234567890123</orderId>" in sent[0] and "<amount>500000</amount>" in sent[0]
    assert "password" not in json.dumps(started.response)


@pytest.mark.asyncio
async def test_behpardakht_rejected_and_xxe_blocked() -> None:
    gw = BehpardakhtGateway(
        CREDS, transport=transport(lambda r: httpx.Response(200, text=soap("421")))
    )
    with pytest.raises(GatewayError) as err:
        await gw.request(context())
    assert err.value.code == "421"
    evil = '<!DOCTYPE x [<!ENTITY a "b">]>' + soap("0")
    with pytest.raises(GatewayError):
        BehpardakhtGateway.parse_return(evil)


@pytest.mark.asyncio
async def test_behpardakht_verify_settle_reverse_codes() -> None:
    returns = iter(["0", "0", "45", "48"])
    ops: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ops.append("bpVerifyRequest" if "bpVerifyRequest" in request.content.decode() else "other")
        return httpx.Response(200, text=soap(next(returns)))

    gw = BehpardakhtGateway(CREDS, transport=transport(handler))
    attempt = AttemptRef(
        "R", 1234567890123, 500_000, {"SaleReferenceId": "SRI", "FinalAmount": "500000"}
    )
    verified = await gw.verify(attempt)
    assert verified.success and verified.amount_rial == 500_000 and verified.ref_id == "SRI"
    assert await gw.inquiry(attempt) is not None
    assert await gw.settle(attempt)  # 45 = already settled
    assert await gw.reverse(attempt)  # 48 = already reversed
    assert ops[0] == "bpVerifyRequest"


@pytest.mark.asyncio
async def test_behpardakht_verify_already_verified_and_failure() -> None:
    gw = BehpardakhtGateway(
        CREDS, transport=transport(lambda r: httpx.Response(200, text=soap("43")))
    )
    ref = AttemptRef("R", 1, 10_000, {"SaleReferenceId": "S"})
    result = await gw.verify(ref)
    assert result.success and result.already_verified
    gw = BehpardakhtGateway(
        CREDS, transport=transport(lambda r: httpx.Response(200, text=soap("42")))
    )
    assert not (await gw.verify(ref)).success


def test_behpardakht_callback() -> None:
    gw = BehpardakhtGateway(CREDS)
    ok = gw.parse_callback(
        {
            "ResCode": "0",
            "RefId": "R",
            "SaleOrderId": "88",
            "SaleReferenceId": "S",
            "FinalAmount": "500000",
            "CardHolderPan": "6104****",
        }
    )
    assert ok.outcome == "ok" and ok.order_ref == 88 and ok.amount_rial == 500_000
    assert gw.parse_callback({"ResCode": "17", "RefId": "R"}).outcome == "canceled"
    assert gw.parse_callback({"ResCode": "0", "RefId": "R"}).outcome == "failed"


# ---- Transport errors -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_network_and_5xx_are_retryable_unknown_outcomes() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    for gw in (
        ZarinpalGateway({"merchant_id": "m"}, transport=transport(boom)),
        BehpardakhtGateway(CREDS, transport=transport(boom)),
    ):
        with pytest.raises(GatewayError) as err:
            await gw.verify(AttemptRef("A", 1, 10_000, {"SaleReferenceId": "S"}))
        assert err.value.retryable

    gw = SamanGateway(
        {"terminal_id": "1"}, transport=transport(lambda r: httpx.Response(503, text="x"))
    )
    with pytest.raises(GatewayError) as err:
        await gw.verify(AttemptRef("T", 1, 10_000, {"RefNum": "R"}))
    assert err.value.retryable


def test_build_gateway_returns_matching_class() -> None:
    assert isinstance(build_gateway("zibal", {"merchant_id": "x"}), ZibalGateway)
    assert not GATEWAYS["zibal"].supports_reverse and GATEWAYS["behpardakht"].needs_settle
