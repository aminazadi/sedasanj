from __future__ import annotations

import httpx

from app.services.gateways.base import Gateway
from app.services.gateways.behpardakht import BehpardakhtGateway
from app.services.gateways.saman import SamanGateway
from app.services.gateways.zarinpal import ZarinpalGateway
from app.services.gateways.zibal import ZibalGateway

GATEWAYS: dict[str, type[Gateway]] = {
    "zarinpal": ZarinpalGateway,
    "zibal": ZibalGateway,
    "saman": SamanGateway,
    "behpardakht": BehpardakhtGateway,
}
# Display order for customers and the admin page.
GATEWAY_ORDER = ("zarinpal", "zibal", "saman", "behpardakht")


def build_gateway(
    code: str,
    credentials: dict[str, str],
    *,
    sandbox: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Gateway:
    return GATEWAYS[code](credentials, sandbox=sandbox, transport=transport)
