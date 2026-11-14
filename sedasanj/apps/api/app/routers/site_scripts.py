"""Super-admin script configuration and CSP-compatible script delivery."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import Field

from app.deps import PublicSession, StaffSession, SuperAdminDep, client_ip
from app.errors import ApiError
from app.models import PlatformSetting
from app.routers.admin import _verify_sensitive_staff_action
from app.services import audit
from app.services.site_scripts import (
    KEY,
    Placement,
    Scope,
    SiteScripts,
    get_settings,
    parse_scripts,
    version,
)

router = APIRouter(prefix="/v1", tags=["site-scripts"])


class ScriptsUpdate(SiteScripts):
    current_password: str = Field(min_length=1, max_length=1024)
    totp_code: str | None = Field(default=None, max_length=10)


@router.get("/admin/site-scripts")
async def admin_scripts(staff: SuperAdminDep, session: StaffSession) -> SiteScripts:
    return await get_settings(session)


@router.put("/admin/site-scripts")
async def save_scripts(
    payload: ScriptsUpdate, request: Request, staff: SuperAdminDep, session: StaffSession
) -> SiteScripts:
    await _verify_sensitive_staff_action(
        session, staff, payload.current_password, payload.totp_code
    )
    settings = SiteScripts(public=payload.public, customer=payload.customer)
    settings.validate_snippets()
    value = settings.model_dump_json()
    row = await session.get(PlatformSetting, KEY)
    if row is None:
        session.add(PlatformSetting(key=KEY, value=value))
    else:
        row.value = value
        row.updated_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="site_scripts.update",
        payload={"updated": True},
        ip=client_ip(request),
    )
    await session.flush()
    return settings


@router.get("/site/scripts/{scope}")
async def script_manifest(
    scope: Scope, session: PublicSession, response: Response
) -> dict[str, list[dict[str, str]]]:
    settings = await get_settings(session)
    slots = getattr(settings, scope)
    result = {}
    for placement in ("head", "body"):
        scripts = parse_scripts(getattr(slots, placement))
        result[placement] = [
            {
                **{key: value for key, value in script.items() if key != "code"},
                "src": script.get("src")
                or (f"/v1/site/scripts/{scope}/{placement}/{index}/{version(script['code'])}.js"),
            }
            for index, script in enumerate(scripts)
        ]
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/site/scripts/{scope}/{placement}/{index}/{digest}.js")
async def inline_script(
    scope: Scope, placement: Placement, index: int, digest: str, session: PublicSession
) -> Response:
    settings = await get_settings(session)
    scripts = parse_scripts(getattr(getattr(settings, scope), placement))
    if index < 0 or index >= len(scripts) or version(scripts[index]["code"]) != digest:
        raise ApiError("not_found", "Script changed; reload the page to load the current version.")
    return Response(
        scripts[index]["code"],
        media_type="text/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
