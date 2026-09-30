from __future__ import annotations

import json

from app.main import create_app


async def test_customer_openapi_excludes_admin_and_declares_security() -> None:
    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/v1/openapi/customer.json"
    )
    response = await route.endpoint()
    schema = json.loads(response.body)
    assert schema["info"]["title"] == "sedasanj (voicesanj)"
    paths = schema["paths"]
    assert "/v1/ingest/calls" in paths
    assert "/v1/ingest/config/validate" in paths
    assert "/v1/auth/api-keys" in paths
    assert not any(path.startswith("/v1/admin") for path in paths)
    assert "TenantCreate" not in schema["components"]["schemas"]
    assert "PlatformKpis" not in schema["components"]["schemas"]
    assert "ApiKeyCreate" in schema["components"]["schemas"]
    assert paths["/v1/ingest/calls"]["post"]["security"] == [
        {"AgentBearer": []},
        {"AgentHeader": []},
    ]
    ingest = paths["/v1/ingest/calls"]["post"]
    assert "AES-256" in ingest["description"]
    assert "Idempotency-Key" in ingest["description"]
    assert {"400", "401", "402", "413", "415", "422", "429"} <= set(
        ingest["responses"]
    )
    assert "CustomerJWT" in schema["components"]["securitySchemes"]
