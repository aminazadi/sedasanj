"""Return page for Jalase-Negar buyers after the bank."""

from __future__ import annotations

from uuid import uuid4

from app.routers import commerce


def test_jalase_buyers_are_sent_to_the_return_page_and_others_keep_the_panel() -> None:
    order = uuid4()
    jalase = commerce._result_redirect(order, "paid", "zarinpal", jalase=True)
    assert "/v1/payments/jalase-return?" in jalase.headers["location"]
    assert f"order={order}" in jalase.headers["location"]
    panel = commerce._result_redirect(order, "paid", "zarinpal")
    assert "/payment-result?" in panel.headers["location"]


async def test_the_return_page_links_back_to_the_app_and_ignores_unknown_status() -> None:
    order = uuid4()
    page = await commerce.jalase_return(order=order, outcome="paid")
    body = bytes(page.body).decode()
    assert f"jalasenegar://payment/result?order={order}&status=paid" in body
    odd = await commerce.jalase_return(order=None, outcome="<script>alert(1)</script>")
    text = bytes(odd.body).decode()
    assert "<script" not in text and "status=pending" in text
