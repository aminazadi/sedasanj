# ruff: noqa: E501 - fixtures copy aapt2/apksigner output verbatim
"""Jalase-Negar Android releases: APK inspection, update selection, range downloads, staff API.

The pure tests run everywhere. The API tests need a disposable PostgreSQL database: set
JALASE_NEGAR_TEST_DSN to its asyncpg URL (the name must contain "test" or "scratch"); the test
creates only the three tables it needs. Never point it at real data.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import zipfile
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

from app.errors import ApiError
from app.services import jalase_negar_releases as apks

CERT = "e7fb6bf31abdfb5d7609bc2149d983ef9b3c161ea19d312a147a8fa196952512"
OTHER_CERT = "a" * 64

BADGING = """package: name='app.jalasenegar.jalase_negar' versionCode='7' versionName='1.2.0' platformBuildVersionName='16'
minSdkVersion:'24'
targetSdkVersion:'36'
native-code: 'arm64-v8a'
"""
MANIFEST = """N: android=http://schemas.android.com/apk/res/android
  E: manifest (line=2)
    A: package="app.jalasenegar.jalase_negar" (Raw: "app.jalasenegar.jalase_negar")
      E: application (line=20)
        A: http://schemas.android.com/apk/res/android:label(0x01010001)="x"
"""
SIGNER = """Verifies
Verified using v1 scheme (JAR signing): false
Verified using v2 scheme (APK Signature Scheme v2): true
Verified using v3 scheme (APK Signature Scheme v3): false
Number of signers: 1
Signer #1 certificate DN: CN=Release
Signer #1 certificate SHA-256 digest: {cert}
"""


def _apk(tmp_path: Path, name: str = "app.apk", *, manifest: bool = True) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        if manifest:
            archive.writestr("AndroidManifest.xml", b"\x03\x00")
        archive.writestr("classes.dex", b"dex")
    return path


class FakeTools:
    """Stands in for aapt2 and apksigner so the tests do not depend on the Android SDK."""

    def __init__(
        self,
        *,
        badging: str = BADGING,
        manifest: str = MANIFEST,
        signer: str | None = None,
        signer_code: int = 0,
        badging_code: int = 0,
    ) -> None:
        self.badging = badging
        self.manifest = manifest
        self.signer = signer if signer is not None else SIGNER.format(cert=CERT)
        self.signer_code = signer_code
        self.badging_code = badging_code

    async def __call__(self, argv: Sequence[str]) -> tuple[int, str]:
        if "badging" in argv:
            return self.badging_code, self.badging
        if "xmltree" in argv:
            return 0, self.manifest
        return self.signer_code, self.signer


@pytest.fixture(autouse=True)
def trusted_certificate(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "jalase_negar_apk_cert_sha256", CERT)


# --- parsing -----------------------------------------------------------------------------------


def test_badging_is_parsed() -> None:
    parsed = apks.parse_badging(BADGING)
    assert parsed["package_name"] == "app.jalasenegar.jalase_negar"
    assert parsed["version_code"] == 7 and parsed["version_name"] == "1.2.0"
    assert parsed["min_sdk"] == 24 and parsed["abis"] == ("arm64-v8a",)


def test_badging_without_package_is_invalid() -> None:
    with pytest.raises(ApiError) as caught:
        apks.parse_badging("nothing useful")
    assert caught.value.code == "apk_invalid"


@pytest.mark.parametrize(
    "line",
    [
        "A: http://schemas.android.com/apk/res/android:debuggable(0x0101000f)=true",
        "A: http://schemas.android.com/apk/res/android:debuggable(0x0101000f)=(type 0x12)0xffffffff",
    ],
)
def test_debuggable_flag_is_detected(line: str) -> None:
    assert apks.manifest_flags(MANIFEST + line)["debuggable"] is True
    assert apks.manifest_flags(MANIFEST)["debuggable"] is False


def test_test_only_and_split_flags() -> None:
    flags = apks.manifest_flags(
        MANIFEST
        + "A: http://schemas.android.com/apk/res/android:testOnly(0x01010272)=(type 0x12)0xffffffff\n"
        + '    A: split="config.arm64_v8a" (Raw: "config.arm64_v8a")\n'
    )
    assert flags["test_only"] and flags["split"]


def test_apksigner_requires_v2_or_newer_and_one_signer() -> None:
    assert apks.parse_apksigner(SIGNER.format(cert=CERT))[1] == [CERT]
    v1_only = SIGNER.format(cert=CERT).replace("v2): true", "v2): false")
    with pytest.raises(ApiError, match="v2"):
        apks.parse_apksigner(v1_only)
    two = SIGNER.format(cert=CERT) + f"Signer #2 certificate SHA-256 digest: {OTHER_CERT}\n"
    with pytest.raises(ApiError, match="exactly one"):
        apks.parse_apksigner(two)
    with pytest.raises(ApiError):
        apks.parse_apksigner("DOES NOT VERIFY\n")


def test_apksigner_warnings_before_the_verdict_are_tolerated() -> None:
    text = "WARNING: something harmless\n" + SIGNER.format(cert=CERT)
    assert apks.parse_apksigner(text)[1] == [CERT]


# --- inspection --------------------------------------------------------------------------------


async def test_inspect_accepts_a_production_apk(tmp_path: Path) -> None:
    inspection = await apks.inspect_apk(_apk(tmp_path), runner=FakeTools())
    assert inspection.version_code == 7 and inspection.version_name == "1.2.0"
    assert inspection.cert_sha256 == CERT and inspection.abis == ("arm64-v8a",)
    assert inspection.size == (tmp_path / "app.apk").stat().st_size


@pytest.mark.parametrize(
    ("tools", "message"),
    [
        (
            FakeTools(badging=BADGING.replace("app.jalasenegar.jalase_negar", "com.other")),
            "package",
        ),
        (FakeTools(signer=SIGNER.format(cert=OTHER_CERT)), "trusted production certificate"),
        (FakeTools(signer_code=1, signer="ERROR: bad"), "signature"),
        (FakeTools(badging_code=1), "manifest"),
        (
            FakeTools(
                manifest=MANIFEST
                + "A: http://schemas.android.com/apk/res/android:debuggable(0x0101000f)=true"
            ),
            "debug",
        ),
        (FakeTools(manifest=MANIFEST + '    A: split="x" (Raw: "x")\n'), "split"),
        (FakeTools(badging=BADGING.replace("1.2.0", "1.2 0")), "versionName"),
    ],
)
async def test_inspect_rejects_unfit_apks(tmp_path: Path, tools: FakeTools, message: str) -> None:
    with pytest.raises(ApiError) as caught:
        await apks.inspect_apk(_apk(tmp_path), runner=tools)
    assert caught.value.code == "apk_invalid" and message in caught.value.message


async def test_inspect_rejects_corrupt_and_bundle_files(tmp_path: Path) -> None:
    broken = tmp_path / "broken.apk"
    broken.write_bytes(b"not a zip at all")
    with pytest.raises(ApiError) as caught:
        await apks.inspect_apk(broken, runner=FakeTools())
    assert caught.value.code == "apk_invalid"
    bundle = tmp_path / "app.aab"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("BundleConfig.pb", b"x")
    with pytest.raises(ApiError, match="app bundle"):
        await apks.inspect_apk(bundle, runner=FakeTools())
    with pytest.raises(ApiError, match="AndroidManifest"):
        await apks.inspect_apk(_apk(tmp_path, "nomanifest.apk", manifest=False), runner=FakeTools())


async def test_inspect_needs_a_configured_certificate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "jalase_negar_apk_cert_sha256", "")
    with pytest.raises(ApiError) as caught:
        await apks.inspect_apk(_apk(tmp_path), runner=FakeTools())
    assert caught.value.code == "apk_inspection_unavailable"


async def test_missing_tools_are_reported_as_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "jalase_negar_aapt2_path", "/nonexistent/aapt2")
    with pytest.raises(ApiError) as caught:
        await apks.inspect_apk(_apk(tmp_path))
    assert caught.value.code == "apk_inspection_unavailable"


SDK = Path(os.environ.get("ANDROID_HOME", Path.home() / "Library/Android/sdk"))
REAL_TOOLS = sorted((SDK / "build-tools").glob("*/aapt2")) if SDK.exists() else []
DEBUG_APK = Path(__file__).parents[2] / "jalase-negar/build/app/outputs/flutter-apk/app-debug.apk"


@pytest.mark.skipif(
    not REAL_TOOLS or not shutil.which("java") or not DEBUG_APK.exists(),
    reason="Android build-tools, Java or the local debug APK are missing",
)
async def test_real_tools_reject_the_local_debug_apk(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    tools = REAL_TOOLS[-1].parent
    monkeypatch.setattr(get_settings(), "jalase_negar_aapt2_path", str(tools / "aapt2"))
    monkeypatch.setattr(get_settings(), "jalase_negar_apksigner_path", str(tools / "apksigner"))
    with pytest.raises(ApiError) as caught:
        await apks.inspect_apk(DEBUG_APK)
    assert caught.value.code == "apk_invalid" and "debug" in caught.value.message


# --- selection ---------------------------------------------------------------------------------


def _release(code: int, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "version_code": code,
        "min_sdk": 24,
        "abis": ["arm64-v8a"],
        "status": "published",
        "signing_cert_sha256": CERT,
        "rollout_percent": 100,
        "min_supported_version_code": 0,
        "channel": "stable",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _pick(rows: list[SimpleNamespace], **device: object) -> SimpleNamespace | None:
    args: dict[str, object] = {
        "version_code": 2,
        "sdk_int": 34,
        "abis": ["arm64-v8a", "armeabi-v7a"],
        "cert_sha256": CERT,
    }
    args.update(device)
    return apks.select_update(rows, **args)  # type: ignore[arg-type]


def test_highest_compatible_published_release_is_chosen() -> None:
    rows = [_release(3), _release(5), _release(4, status="revoked"), _release(6, status="draft")]
    assert _pick(rows).version_code == 5  # type: ignore[union-attr]


def test_no_offer_for_equal_or_newer_installs() -> None:
    rows = [_release(3)]
    assert _pick(rows, version_code=3) is None
    assert _pick(rows, version_code=9) is None


@pytest.mark.parametrize(
    "device",
    [
        {"sdk_int": 23},
        {"abis": ["x86_64"]},
        {"cert_sha256": OTHER_CERT},
        {"cert_sha256": None},
    ],
)
def test_incompatible_devices_get_no_offer(device: dict[str, object]) -> None:
    assert _pick([_release(3)], **device) is None


def test_apk_without_native_code_fits_any_abi() -> None:
    assert _pick([_release(3, abis=[])], abis=["x86_64"]) is not None


def test_incompatible_newest_falls_back_to_the_best_compatible() -> None:
    rows = [_release(3), _release(5, min_sdk=35)]
    assert _pick(rows).version_code == 3  # type: ignore[union-attr]


def test_revoked_release_falls_back_to_the_earlier_one_for_lower_builds_only() -> None:
    rows = [_release(3), _release(4, status="revoked")]
    assert _pick(rows, version_code=2).version_code == 3  # type: ignore[union-attr]
    assert _pick(rows, version_code=4) is None  # already on the revoked build: wait for a fix


def test_abi_list_validation() -> None:
    assert apks.parse_abis("arm64-v8a, armeabi-v7a") == ["arm64-v8a", "armeabi-v7a"]
    assert apks.parse_abis("") == []
    with pytest.raises(ApiError):
        apks.parse_abis("arm64;rm -rf")


def test_certificate_normalisation() -> None:
    assert apks.normalize_cert(CERT.upper()) == CERT
    assert apks.normalize_cert(None) is None
    assert apks.normalize_cert("zz") is None


# --- ranges and orphans ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=0-9", (0, 9)),
        ("bytes=5-", (5, 99)),
        ("bytes=-10", (90, 99)),
        ("bytes=90-500", (90, 99)),
        ("bytes=100-", None),
        ("bytes=9-3", None),
        ("bytes=-0", None),
        ("bytes=0-1,5-6", None),
        ("items=0-1", None),
    ],
)
def test_range_parsing(header: str, expected: tuple[int, int] | None) -> None:
    assert apks.parse_range(header, 100) == expected


def test_orphans_respect_the_grace_period() -> None:
    known, gone, fresh = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    old = now - timedelta(days=1)
    stored = [
        (apks.artifact_key(known, "1.0.0"), old),
        (apks.artifact_key(gone, "1.0.1"), old),
        (apks.artifact_key(fresh, "1.0.2"), now),
        ("jalase-negar-releases/not-a-uuid/x.apk", old),
    ]
    assert apks.orphan_keys(stored, {known}, now=now) == [apks.artifact_key(gone, "1.0.1")]


# --- staff and public API against a disposable PostgreSQL ---------------------------------

TEST_DSN = os.environ.get("JALASE_NEGAR_TEST_DSN")
needs_database = pytest.mark.skipif(not TEST_DSN, reason="disposable PostgreSQL DSN not supplied")

PASSWORD = "correct horse battery"


def _meta(code: int, name: str | None = None, **extra: object) -> bytes:
    return json.dumps({"code": code, "name": name or f"1.0.{code}", **extra}).encode()


async def _fake_inspect(path: Path, **_: object) -> apks.ApkInspection:
    data = json.loads(path.read_bytes())
    if data.get("invalid"):
        raise ApiError("apk_invalid", "the APK signature is not valid; sign the APK again")
    import hashlib

    return apks.ApkInspection(
        package_name=apks.PACKAGE_NAME,
        version_name=data["name"],
        version_code=data["code"],
        min_sdk=data.get("min_sdk", 24),
        abis=tuple(data.get("abis", ["arm64-v8a"])),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size=path.stat().st_size,
        cert_sha256=CERT,
    )


class Env:
    def __init__(self, client: httpx.AsyncClient, storage: object) -> None:
        self.client = client
        self.storage = storage
        self.admin: dict[str, str] = {}
        self.support: dict[str, str] = {}
        self.admin_id = uuid4()

    async def upload(self, code: int, **kwargs: object) -> httpx.Response:
        body = kwargs.pop("body", None)
        files = {"file": ("app.apk", body if body is not None else _meta(code, **kwargs))}
        return await self.client.post(
            "/v1/admin/jalase-negar/releases",
            files=files,
            data={"title": f"v{code}"},
            headers=self.admin,
        )

    async def publish(
        self, release_id: str, *, password: str = PASSWORD, notes: str | None = "<p>تغییرات</p>"
    ) -> httpx.Response:
        if notes is not None:
            patched = await self.client.patch(
                f"/v1/admin/jalase-negar/releases/{release_id}",
                json={"changelog_html": notes},
                headers=self.admin,
            )
            assert patched.status_code == 200, patched.text
        return await self.client.post(
            f"/v1/admin/jalase-negar/releases/{release_id}/publish",
            json={"current_password": password},
            headers=self.admin,
        )

    async def revoke(self, release_id: str) -> httpx.Response:
        return await self.client.post(
            f"/v1/admin/jalase-negar/releases/{release_id}/revoke",
            json={"current_password": PASSWORD},
            headers=self.admin,
        )

    async def check(self, code: int = 1, **overrides: object) -> httpx.Response:
        params: dict[str, object] = {
            "version_code": code,
            "sdk_int": 34,
            "abis": "arm64-v8a",
            "cert_sha256": CERT,
        }
        params.update(overrides)
        return await self.client.get("/v1/jalase-negar/android/update", params=params)  # type: ignore[arg-type]


@pytest.fixture()
async def env(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Env]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app import db
    from app.config import get_settings
    from app.models import AuditEvent, Base, JalaseNegarRelease, StaffUser
    from app.security import create_access_token, hash_password
    from app.services import ratelimit
    from app.services.storage import MemoryStorage, set_storage

    assert TEST_DSN
    database = TEST_DSN.rsplit("/", 1)[-1]
    assert "test" in database or "scratch" in database, "refusing to run on a non-test database"
    monkeypatch.setenv("DATABASE_URL", TEST_DSN)
    monkeypatch.setenv("QUEUE_BACKEND", "memory")
    monkeypatch.setenv("TENANT_DATABASES_ENABLED", "false")
    monkeypatch.setenv("JALASE_NEGAR_APK_CERT_SHA256", CERT)
    get_settings.cache_clear()
    await db.dispose_engine()
    ratelimit._memory.clear()
    engine = create_async_engine(TEST_DSN)
    tables = [StaffUser.__table__, AuditEvent.__table__, JalaseNegarRelease.__table__]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.drop_all(sync, tables=tables))
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    await engine.dispose()

    storage = MemoryStorage()
    set_storage(storage)
    monkeypatch.setattr(apks, "inspect_apk", _fake_inspect)

    from app.main import create_app

    transport = httpx.ASGITransport(app=create_app(), client=("203.0.113.7", 4000))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        env = Env(client, storage)
        async with db.session_scope(staff=True) as session:
            admin = StaffUser(
                email=f"a{uuid4().hex[:6]}@example.com",
                password_hash=hash_password(PASSWORD),
                role="super_admin",
            )
            support = StaffUser(
                email=f"s{uuid4().hex[:6]}@example.com",
                password_hash=hash_password(PASSWORD),
                role="support",
            )
            session.add_all([admin, support])
            await session.flush()
            env.admin_id = admin.id
            for role, user, target in (
                ("super_admin", admin, env.admin),
                ("support", support, env.support),
            ):
                token = create_access_token(
                    subject=user.id, tenant_id=None, role=role, actor="staff"
                )
                target["Authorization"] = f"Bearer {token}"
        yield env
    set_storage(None)
    await db.dispose_engine()
    async with create_async_engine(TEST_DSN).begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS jalase_negar_releases"))
    get_settings.cache_clear()


async def _audit_actions(env: Env) -> list[str]:
    from sqlalchemy import select

    from app import db
    from app.models import AuditEvent

    async with db.session_scope(staff=True) as session:
        rows = (
            await session.execute(
                select(AuditEvent.action, AuditEvent.actor_id, AuditEvent.payload).where(
                    AuditEvent.action.like("jalase_negar_release.%")
                )
            )
        ).all()
    assert all(row.actor_id == env.admin_id for row in rows)
    assert all("release_id" in row.payload for row in rows)
    return [row.action for row in rows]


@needs_database
async def test_staff_can_view_but_only_super_admin_can_change(env: Env) -> None:
    assert (await env.client.get("/v1/admin/jalase-negar/releases")).status_code == 401
    listed = await env.client.get("/v1/admin/jalase-negar/releases", headers=env.support)
    assert listed.status_code == 200 and listed.json()["total"] == 0
    denied = await env.client.post(
        "/v1/admin/jalase-negar/releases",
        files={"file": ("a.apk", _meta(5))},
        headers=env.support,
    )
    assert denied.status_code == 403


@needs_database
async def test_draft_lifecycle_with_audit(env: Env) -> None:
    created = await env.upload(5)
    assert created.status_code == 201, created.text
    release = created.json()
    assert release["status"] == "draft" and release["version_code"] == 5
    assert release["signing_cert_sha256"] == CERT and release["abis"] == ["arm64-v8a"]

    early = await env.publish(release["id"], notes=None)
    assert early.status_code == 422  # no release notes yet

    wrong = await env.publish(release["id"], password="wrong password")
    assert wrong.status_code == 401

    published = await env.publish(release["id"])
    assert published.status_code == 200 and published.json()["status"] == "published"
    assert published.json()["changelog_plain"] == "تغییرات"
    again = await env.publish(release["id"], notes=None)
    assert again.status_code == 200  # idempotent

    revoked = await env.revoke(release["id"])
    assert revoked.json()["status"] == "revoked" and revoked.json()["revoked_at"]
    assert (await env.publish(release["id"], notes=None)).status_code == 409
    actions = await _audit_actions(env)
    assert actions[0] == "jalase_negar_release.create"
    assert actions.count("jalase_negar_release.publish") == 1
    assert actions[-1] == "jalase_negar_release.revoke"


@needs_database
async def test_notes_are_sanitised(env: Env) -> None:
    release = (await env.upload(5)).json()
    patched = await env.client.patch(
        f"/v1/admin/jalase-negar/releases/{release['id']}",
        json={"changelog_html": '<p onclick="x()">متن</p><script>alert(1)</script>'},
        headers=env.admin,
    )
    body = patched.json()
    assert "script" not in body["changelog_html"] and "onclick" not in body["changelog_html"]
    assert body["changelog_plain"] == "متن"


@needs_database
async def test_invalid_apk_and_duplicates_are_refused(env: Env) -> None:
    bad = await env.upload(5, invalid=True)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "apk_invalid"
    assert (await env.upload(5)).status_code == 201
    duplicate_code = await env.upload(5, name="9.9.9")
    duplicate_name = await env.upload(6, name="1.0.5")
    for response in (duplicate_code, duplicate_name):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "release_version_conflict"


@needs_database
async def test_version_code_must_beat_every_published_and_revoked_release(env: Env) -> None:
    first = (await env.upload(10)).json()
    await env.publish(first["id"])
    await env.revoke(first["id"])
    lower = await env.upload(9)
    assert lower.status_code == 409 and "10" in lower.json()["error"]["message"]
    assert (await env.upload(11)).status_code == 201


@needs_database
async def test_publish_rejects_a_draft_that_became_stale(env: Env) -> None:
    older = (await env.upload(5)).json()
    newer = (await env.upload(6)).json()
    assert (await env.publish(newer["id"])).status_code == 200
    stale = await env.publish(older["id"])
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "release_version_conflict"


@needs_database
async def test_concurrent_publishes_keep_version_codes_in_order(env: Env) -> None:
    drafts = [(await env.upload(code)).json() for code in (20, 21, 22, 23)]
    for draft in drafts:
        await env.client.patch(
            f"/v1/admin/jalase-negar/releases/{draft['id']}",
            json={"changelog_html": "<p>x</p>"},
            headers=env.admin,
        )
    results = await asyncio.gather(
        *(
            env.client.post(
                f"/v1/admin/jalase-negar/releases/{draft['id']}/publish",
                json={"current_password": PASSWORD},
                headers=env.admin,
            )
            for draft in reversed(drafts)
        )
    )
    assert {response.status_code for response in results} <= {200, 409}
    published = (
        await env.client.get("/v1/admin/jalase-negar/releases?status=published", headers=env.admin)
    ).json()["items"]
    ordered = sorted(published, key=lambda item: item["published_at"])
    assert [item["version_code"] for item in ordered] == sorted(
        item["version_code"] for item in ordered
    )
    assert published, "at least one publication must win"


@needs_database
async def test_storage_failure_leaves_no_draft(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(*_: object, **__: object) -> None:
        raise ConnectionError("minio is down")

    monkeypatch.setattr(env.storage, "put_path", broken)
    failed = await env.upload(5)
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "release_file_unavailable"
    listing = await env.client.get("/v1/admin/jalase-negar/releases", headers=env.admin)
    assert listing.json()["total"] == 0


@needs_database
async def test_publish_needs_the_stored_file(env: Env) -> None:
    release = (await env.upload(5)).json()
    env.storage.objects.clear()  # type: ignore[attr-defined]
    response = await env.publish(release["id"])
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "release_file_unavailable"


@needs_database
async def test_update_check_follows_compatibility_and_revocation(env: Env) -> None:
    low = (await env.upload(5)).json()
    high = (await env.upload(7)).json()
    await env.publish(low["id"])
    await env.publish(high["id"])

    offer = (await env.check(code=2)).json()["update"]
    assert offer["version_code"] == 7 and offer["notes"] == "تغییرات"
    assert offer["download_path"] == f"/v1/jalase-negar/android/releases/{high['id']}/download"
    assert offer["id"] == high["id"] and offer["size"] > 0

    checked = await env.check(code=2)
    assert checked.headers["cache-control"] == "no-store"
    assert (await env.check(code=7)).json() == {"update": None}
    assert (await env.check(code=2, sdk_int=20)).json() == {"update": None}
    assert (await env.check(code=2, abis="x86_64")).json() == {"update": None}
    assert (await env.check(code=2, cert_sha256=OTHER_CERT)).json() == {"update": None}
    assert (await env.check(code=2, cert_sha256="")).json() == {"update": None}

    await env.revoke(high["id"])
    assert (await env.check(code=2)).json()["update"]["version_code"] == 5
    assert (await env.check(code=5)).json() == {"update": None}
    assert (await env.check(code=7)).json() == {"update": None}


@needs_database
async def test_update_check_validates_input(env: Env) -> None:
    assert (await env.check(code=0)).status_code == 422
    assert (await env.check(abis="a;b")).status_code == 422


@needs_database
async def test_update_check_is_rate_limited(env: Env) -> None:
    statuses = [(await env.check()).status_code for _ in range(62)]
    assert statuses[0] == 200 and 429 in statuses


@needs_database
async def test_download_streams_ranges_and_stops_after_revoke(env: Env) -> None:
    body = _meta(5, pad="x" * 400)
    release = (await env.upload(5, body=body)).json()
    await env.publish(release["id"])
    url = f"/v1/jalase-negar/android/releases/{release['id']}/download"

    full = await env.client.get(url)
    assert full.status_code == 200 and full.content == body
    assert full.headers["content-type"] == apks.APK_MIME
    assert full.headers["content-length"] == str(len(body))
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["cache-control"] == "no-store"
    assert 'filename="jalase-negar-1.0.5.apk"' in full.headers["content-disposition"]

    part = await env.client.get(url, headers={"Range": "bytes=10-49"})
    assert part.status_code == 206 and part.content == body[10:50]
    assert part.headers["content-range"] == f"bytes 10-49/{len(body)}"
    assert part.headers["content-length"] == "40"

    resume = await env.client.get(url, headers={"Range": f"bytes={len(body) - 5}-"})
    assert resume.status_code == 206 and resume.content == body[-5:]

    stale_validator = await env.client.get(
        url, headers={"Range": "bytes=0-9", "If-Range": '"deadbeef"'}
    )
    assert stale_validator.status_code == 200 and stale_validator.content == body

    outside = await env.client.get(url, headers={"Range": f"bytes={len(body)}-"})
    assert outside.status_code == 416
    assert outside.headers["content-range"] == f"bytes */{len(body)}"

    await env.revoke(release["id"])
    gone = await env.client.get(url)
    assert gone.status_code == 404 and gone.headers["cache-control"] == "no-store"


@needs_database
async def test_download_of_unknown_or_draft_release_is_not_found(env: Env) -> None:
    draft = (await env.upload(5)).json()
    for release_id in (draft["id"], str(uuid4())):
        response = await env.client.get(f"/v1/jalase-negar/android/releases/{release_id}/download")
        assert response.status_code == 404


@needs_database
async def test_missing_file_is_reported_with_its_own_code(env: Env) -> None:
    release = (await env.upload(5)).json()
    await env.publish(release["id"])
    env.storage.objects.clear()  # type: ignore[attr-defined]
    response = await env.client.get(f"/v1/jalase-negar/android/releases/{release['id']}/download")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "release_file_unavailable"
    assert response.json()["error"]["retryable"] is True


@needs_database
async def test_admin_download_works_for_drafts(env: Env) -> None:
    release = (await env.upload(5)).json()
    response = await env.client.get(
        f"/v1/admin/jalase-negar/releases/{release['id']}/download", headers=env.admin
    )
    assert response.status_code == 200 and response.content == _meta(5)
    assert (
        await env.client.get(f"/v1/admin/jalase-negar/releases/{release['id']}/download")
    ).status_code == 401


@needs_database
async def test_only_drafts_can_be_deleted_and_the_file_goes_too(env: Env) -> None:
    draft = (await env.upload(5)).json()
    live = (await env.upload(6)).json()
    await env.publish(live["id"])
    refused = await env.client.delete(
        f"/v1/admin/jalase-negar/releases/{live['id']}", headers=env.admin
    )
    assert refused.status_code == 422
    key = apks.artifact_key(UUID(draft["id"]), "1.0.5")
    assert key in env.storage.objects  # type: ignore[attr-defined]
    removed = await env.client.delete(
        f"/v1/admin/jalase-negar/releases/{draft['id']}", headers=env.admin
    )
    assert removed.status_code == 204
    assert (
        await env.client.get(f"/v1/admin/jalase-negar/releases/{draft['id']}", headers=env.admin)
    ).status_code == 404
    assert key not in env.storage.objects  # type: ignore[attr-defined]


@needs_database
async def test_sweeper_collects_files_without_a_row(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings
    from app.routers.jalase_negar_releases import sweep_orphan_files

    kept = (await env.upload(5)).json()
    stray = apks.artifact_key(uuid4(), "9.9.9")
    fresh = apks.artifact_key(uuid4(), "9.9.8")
    storage = env.storage
    await storage.put(stray, b"x")  # type: ignore[attr-defined]
    await storage.put(fresh, b"x")  # type: ignore[attr-defined]
    storage.modified[stray] = datetime.now(UTC) - timedelta(days=2)  # type: ignore[attr-defined]
    assert get_settings().jalase_negar_orphan_grace_minutes < 2 * 24 * 60
    assert await sweep_orphan_files() == 1
    objects = storage.objects  # type: ignore[attr-defined]
    assert stray not in objects and fresh in objects
    assert apks.artifact_key(UUID(kept["id"]), "1.0.5") in objects


@needs_database
async def test_oversized_upload_is_refused_up_front(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_jalase_negar_apk_bytes", 1024)
    huge = await env.client.post(
        "/v1/admin/jalase-negar/releases",
        content=b"x" * (3 * 1024 * 1024),
        headers={**env.admin, "Content-Type": "multipart/form-data; boundary=x"},
    )
    assert huge.status_code == 413 and huge.json()["error"]["code"] == "archive_too_large"
    streamed = await env.upload(5, body=b"x" * 2048)
    assert streamed.status_code == 413
