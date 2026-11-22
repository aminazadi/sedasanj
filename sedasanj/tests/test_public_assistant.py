"""Public, unauthenticated هوشیار widget: route wiring and prompt assembly (no database)."""

from __future__ import annotations

from plan_routes import api_routes, dependency_calls

from app import deps
from app.main import create_app
from app.routers import public_assistant


def test_public_assistant_route_exists_and_is_hidden_from_the_schema() -> None:
    route = next(r for r in api_routes() if r.path == "/v1/public-assistant/messages/stream")
    assert "POST" in route.methods
    assert route.include_in_schema is False


def test_public_assistant_route_requires_neither_user_nor_api_key() -> None:
    routes = [r for r in api_routes() if r.path.startswith("/v1/public-assistant")]
    assert routes
    for route in routes:
        calls = dependency_calls(route.dependant)
        assert deps.current_user not in calls, route.path
        assert deps.current_api_key not in calls, route.path


def test_public_assistant_route_is_outside_the_tenant_assistant_prefix() -> None:
    # test_assistant_isolation.py requires every /v1/assistant route to need a tenant user;
    # the public widget must never live under that prefix or it would be caught by that rule.
    routes = [r for r in api_routes() if r.path.startswith("/v1/public-assistant")]
    assert routes
    for route in routes:
        assert not route.path.startswith("/v1/assistant"), route.path


async def test_customer_openapi_never_lists_public_assistant_routes() -> None:
    import json

    app = create_app()
    route = next(r for r in app.routes if getattr(r, "path", None) == "/v1/openapi/customer.json")
    paths = json.loads((await route.endpoint()).body)["paths"]
    assert not [p for p in paths if "public-assistant" in p]


async def test_public_assistant_prompt_never_exposes_tenant_data_instructions(
    monkeypatch,
) -> None:
    async def fixed_instructions(_session: object) -> str:
        return "صداسنج یک پلتفرم تحلیل تماس است."

    monkeypatch.setattr(
        public_assistant, "effective_public_assistant_instructions", fixed_instructions
    )
    prompt = await public_assistant._public_assistant_system_prompt(object())

    assert "صداسنج یک پلتفرم تحلیل تماس است." in prompt
    assert "هیچ ابزار یا دسترسی به پایگاه داده نداری" in prompt
    assert "فقط به سؤالات دربارهٔ محصولات صداسنج و جلسه‌نگار" in prompt


async def test_public_assistant_prompt_falls_back_to_the_packaged_seed(
    monkeypatch,
) -> None:
    from app.services import platform

    async def no_row(_session: object) -> str:
        from worker_llm.client import load_prompt

        return load_prompt(platform.PUBLIC_ASSISTANT_SEED_VERSION)

    monkeypatch.setattr(public_assistant, "effective_public_assistant_instructions", no_row)
    prompt = await public_assistant._public_assistant_system_prompt(object())

    assert "صداسنج" in prompt
    assert "جلسه‌نگار" in prompt
