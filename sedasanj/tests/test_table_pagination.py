"""Panel validators accept 200 rows and retain the existing validation error contract."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from typing import get_type_hints

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.errors import install_error_handlers
from app.routers import (
    admin,
    auth,
    billing,
    calls,
    commerce,
    contacts,
    help,
    kpi,
    module_updates,
    scheduled_reports,
    webhooks,
)
from app.services.help_content import sanitize_help_html


def panel_limits():
    for module in (
        admin,
        auth,
        billing,
        calls,
        commerce,
        contacts,
        help,
        kpi,
        module_updates,
        scheduled_reports,
        webhooks,
    ):
        for route in module.router.routes:
            if not isinstance(route, APIRoute):
                continue
            if module is help and not route.path.startswith("/v1/admin/"):
                continue
            parameters = inspect.signature(route.endpoint).parameters
            for key in ("limit", "table_limit"):
                if key not in parameters:
                    continue
                parameter = parameters[key]
                annotation = get_type_hints(route.endpoint, include_extras=True)[key]
                yield pytest.param(
                    parameter.replace(name="limit", annotation=annotation),
                    id=f"{module.__name__}.{route.name}.{key}",
                )


@pytest.mark.parametrize("parameter", list(panel_limits()))
def test_panel_limit_accepts_200_and_rejects_invalid_values(parameter) -> None:
    app = FastAPI()
    install_error_handlers(app)

    async def endpoint(limit):
        return {"limit": limit}

    endpoint.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        [parameter]
    )
    app.get("/rows")(endpoint)
    with TestClient(app) as client:
        for size in (10, 25, 50, 100, 200):
            response = client.get("/rows", params={"limit": size})
            assert response.status_code == 200, response.text
            assert response.json() == {"limit": size}
        for size in (0, -1, 201, "abc"):
            response = client.get("/rows", params={"limit": size})
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "invalid_request"


def test_pagination_help_article_preserves_instructions_and_error_code() -> None:
    path = (
        Path(__file__).parents[1]
        / "apps/api/alembic/versions/0090_table_pagination_help_content.py"
    )
    spec = importlib.util.spec_from_file_location("table_pagination_help", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cleaned, plain = sanitize_help_html(module.ARTICLE_BODY)
    assert module.down_revision == "0089_contacts_import_help_content"
    assert "page_size" in plain
    assert "invalid_request" in plain
    assert "۲۰۰" in plain
    assert "<ol>" in cleaned
    assert 'dir="ltr"' in module.ARTICLE_BODY
    assert "<code>page_size</code>" in cleaned
