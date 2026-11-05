"""ML model registry: storage keys, retention, publisher auth, upload rules, admin API.

The pure tests run everywhere. The API tests need a disposable PostgreSQL database: set
ML_MODEL_TEST_DSN to its asyncpg URL (the database name must contain "test" or "scratch"); the
tests create only the tables they need. Never point it at real data.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import httpx
import pytest

from app.errors import ERROR_STATUS
from app.services import ml_models
from app.services.api_scopes import API_KEY_SCOPES, MEETING_SCOPE, ML_PUBLISH_SCOPE
from app.services.tenant_provisioning import _CONTROL_ONLY

VERSIONS = Path(__file__).parents[1] / "apps/api/alembic/versions"
CODES = {
    "ml_model_not_found",
    "ml_model_checksum_mismatch",
    "ml_model_invalid",
    "ml_model_version_conflict",
    "ml_publish_forbidden",
}
PASSWORD = "correct horse battery"


def _onnx(seed: str = "a", size: int = 2048) -> bytes:
    # ONNX ModelProto starts with the ir_version field tag (0x08).
    return b"\x08\x08" + (seed.encode() * size)[:size]


def _meta(data: bytes, version: str = "1.0.0", **extra: object) -> str:
    body: dict[str, object] = {
        "kind": "speaker_embedding",
        "version": version,
        "sha256": hashlib.sha256(data).hexdigest(),
        "dim": 192,
        "sample_rate": 16000,
        "metrics": {"eer": 0.031},
        "dataset_manifest_hash": "m" * 16,
        "training_run_id": "run-1",
    }
    body.update(extra)
    return json.dumps(body)


# --- pure tests ----


def test_scope_is_not_available_from_the_panel() -> None:
    assert ML_PUBLISH_SCOPE == "ml:publish"
    assert ML_PUBLISH_SCOPE not in API_KEY_SCOPES
    assert MEETING_SCOPE != ML_PUBLISH_SCOPE


def test_table_is_control_plane_only() -> None:
    assert "ml_model_releases" in _CONTROL_ONLY


def test_error_codes_are_registered() -> None:
    assert set(ERROR_STATUS) >= CODES
    assert ERROR_STATUS["ml_model_not_found"] == 404
    assert ERROR_STATUS["ml_model_version_conflict"] == 409
    assert ERROR_STATUS["ml_publish_forbidden"] == 403


def test_every_code_has_a_persian_help_article() -> None:
    spec = importlib.util.spec_from_file_location(
        "ml_help_migration", VERSIONS / "0111_ml_model_help_content.py"
    )
    assert spec and spec.loader
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert {code for code, *_ in module.ERRORS} == CODES
    for _, title, _, cause, steps, quick in module.ERRORS:
        assert any("؀" <= ch <= "ۿ" for ch in title + cause + quick)
        assert steps


def test_migrations_have_one_head_after_the_merge() -> None:
    revisions: dict[str, tuple[str, ...]] = {}
    for path in VERSIONS.glob("*.py"):
        spec = importlib.util.spec_from_file_location(f"mig_{path.stem}", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        down = module.down_revision
        revisions[module.revision] = (
            () if down is None else (down,) if isinstance(down, str) else tuple(down)
        )
    referenced = {parent for parents in revisions.values() for parent in parents}
    assert [rev for rev in revisions if rev not in referenced] == ["0111_ml_model_help_content"]


def test_migration_follows_the_conventions() -> None:
    text = (VERSIONS / "0110_ml_model_releases.py").read_text()
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ml_model_releases TO cbi_app" in text
    assert "def downgrade" in text and "drop_table" in text
    assert text.count("op.execute(") == 3
    assert ";" not in "".join(
        line for line in text.splitlines() if "op.execute" in line or line.strip().startswith('"')
    ).replace("';'", "")


def test_keys_stay_under_the_prefix_and_round_trip() -> None:
    release_id = uuid4()
    key = ml_models.artifact_key(release_id, "speaker_embedding", "1.0.0")
    assert key.startswith("ml-models/")
    assert ml_models.release_id_from_key(key) == release_id
    assert ml_models.release_id_from_key("ml-models/oops") is None
    assert ml_models.release_id_from_key("jalase-negar-releases/a/b/c") is None


def test_orphans_respect_the_grace_period() -> None:
    now = datetime.now(UTC)
    known, orphan, fresh = uuid4(), uuid4(), uuid4()
    stored = [
        (ml_models.artifact_key(known, "k", "1"), now - timedelta(days=1)),
        (ml_models.artifact_key(orphan, "k", "2"), now - timedelta(days=1)),
        (ml_models.artifact_key(fresh, "k", "3"), now - timedelta(minutes=5)),
        ("ml-models/unrelated.txt", now - timedelta(days=1)),
    ]
    assert ml_models.orphan_keys(stored, {known}, now=now) == [stored[1][0]]


def test_retention_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.config import get_settings

    monkeypatch.setenv("ML_MODEL_PREV_RETENTION_HOURS", "72")
    get_settings.cache_clear()
    now = datetime.now(UTC)

    def row(**kw: object) -> SimpleNamespace:
        base = {
            "channel": "champion",
            "status": "ready",
            "pinned": False,
            "superseded_at": now - timedelta(hours=73),
        }
        base.update(kw)
        return SimpleNamespace(**base)

    assert ml_models.retention_expired(row(), now=now)  # type: ignore[arg-type]
    assert not ml_models.retention_expired(row(superseded_at=now - timedelta(hours=71)), now=now)  # type: ignore[arg-type]
    assert not ml_models.retention_expired(row(pinned=True), now=now)  # type: ignore[arg-type]
    assert not ml_models.retention_expired(row(superseded_at=None), now=now)  # type: ignore[arg-type]
    assert not ml_models.retention_expired(row(channel="latest"), now=now)  # type: ignore[arg-type]
    get_settings.cache_clear()


# --- API against a disposable PostgreSQL ---------------------------------------------------

TEST_DSN = os.environ.get("ML_MODEL_TEST_DSN")
needs_database = pytest.mark.skipif(not TEST_DSN, reason="disposable PostgreSQL DSN not supplied")


class Env:
    def __init__(self, client: httpx.AsyncClient, storage: object) -> None:
        self.client = client
        self.storage = storage
        self.tenant_id = uuid4()
        self.key = ""
        self.admin: dict[str, str] = {}
        self.support: dict[str, str] = {}
        self.admin_id = uuid4()

    @property
    def publisher(self) -> dict[str, str]:
        return {"X-API-Key": self.key}

    async def publish(
        self,
        data: bytes,
        *,
        version: str = "1.0.0",
        channel: str = "latest",
        meta: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self.client.post(
            "/v1/ml/models",
            params={"channel": channel},
            files={"file": ("model.onnx", data)},
            data={"metadata": meta if meta is not None else _meta(data, version)},
            headers=headers if headers is not None else self.publisher,
        )

    async def action(self, model_id: str, name: str, **body: object) -> httpx.Response:
        return await self.client.post(
            f"/v1/admin/ml/models/{model_id}/{name}",
            json={"current_password": PASSWORD, **body},
            headers=self.admin,
        )

    async def listing(self, **params: str) -> list[dict[str, object]]:
        response = await self.client.get("/v1/admin/ml/models", params=params, headers=self.admin)
        assert response.status_code == 200, response.text
        return response.json()["items"]  # type: ignore[no-any-return]


async def _make_key(
    env: Env, *, cidrs: list[str], scopes: list[str], kind: str = "integration"
) -> str:
    from app import db
    from app.models import ApiKey
    from app.security import generate_api_key

    secret, prefix, key_hash = generate_api_key()
    async with db.session_scope(None, staff=True) as session:
        session.add(
            ApiKey(
                tenant_id=env.tenant_id,
                key_hash=key_hash,
                key_prefix=prefix,
                scopes=scopes,
                allowed_cidrs=cidrs,
                kind=kind,
            )
        )
    return secret


@pytest.fixture()
async def env(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Env]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app import db
    from app.config import get_settings
    from app.models import ApiKey, AuditEvent, Base, MlModelRelease, StaffUser, Tenant, User
    from app.security import create_access_token, hash_password
    from app.services import ratelimit
    from app.services.storage import MemoryStorage, set_storage

    assert TEST_DSN
    database = TEST_DSN.rsplit("/", 1)[-1]
    assert "test" in database or "scratch" in database, "refusing to run on a non-test database"
    tenant_id = uuid4()
    monkeypatch.setenv("DATABASE_URL", TEST_DSN)
    monkeypatch.setenv("QUEUE_BACKEND", "memory")
    monkeypatch.setenv("TENANT_DATABASES_ENABLED", "false")
    monkeypatch.setenv("ML_PUBLISHER_TENANT_ID", str(tenant_id))
    monkeypatch.setenv("ML_MODEL_PREV_RETENTION_HOURS", "72")
    monkeypatch.setenv("MAX_ML_MODEL_BYTES", "1048576")
    get_settings.cache_clear()
    await db.dispose_engine()
    ratelimit._memory.clear()
    engine = create_async_engine(TEST_DSN)
    tables = [
        Tenant.__table__,
        User.__table__,
        ApiKey.__table__,
        StaffUser.__table__,
        AuditEvent.__table__,
        MlModelRelease.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.drop_all(sync, tables=tables))
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    await engine.dispose()

    storage = MemoryStorage()
    set_storage(storage)

    from app.main import create_app

    transport = httpx.ASGITransport(app=create_app(), client=("203.0.113.7", 4000))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        env = Env(client, storage)
        env.tenant_id = tenant_id
        async with db.session_scope(staff=True) as session:
            session.add(Tenant(id=tenant_id, name="platform", price_per_minute_toman=0))
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
        env.key = await _make_key(env, cidrs=["203.0.113.0/24"], scopes=[ML_PUBLISH_SCOPE])
        yield env
    set_storage(None)
    await db.dispose_engine()
    async with create_async_engine(TEST_DSN).begin() as connection:
        for name in (
            "ml_model_releases",
            "api_keys",
            "users",
            "audit_events",
            "staff_users",
            "tenants",
        ):
            await connection.execute(text(f"DROP TABLE IF EXISTS {name} CASCADE"))
    get_settings.cache_clear()


async def _audit_actions(prefix: str) -> list[str]:
    from sqlalchemy import select

    from app import db
    from app.models import AuditEvent

    async with db.session_scope(staff=True) as session:
        rows = (
            await session.execute(select(AuditEvent.action).where(AuditEvent.action.like(prefix)))
        ).scalars()
        return list(rows)


@needs_database
async def test_publish_stores_the_model_and_returns_metadata(env: Env) -> None:
    data = _onnx()
    response = await env.publish(data)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready" and body["channel"] == "latest"
    assert body["sha256"] == hashlib.sha256(data).hexdigest()
    assert body["size_bytes"] == len(data) and body["dim"] == 192
    assert "artifact_key" not in body
    keys = await env.storage.list_keys("ml-models/")  # type: ignore[attr-defined]
    assert len(keys) == 1 and keys[0][0].startswith("ml-models/speaker_embedding/")
    assert await _audit_actions("ml_model.publish") == ["ml_model.publish"]


@needs_database
async def test_wrong_sha256_is_rejected_and_nothing_is_stored(env: Env) -> None:
    data = _onnx()
    response = await env.publish(data, meta=_meta(data, sha256="0" * 64))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ml_model_checksum_mismatch"
    assert await env.storage.list_keys("ml-models/") == []  # type: ignore[attr-defined]
    assert await env.listing() == []


@needs_database
async def test_republishing_the_same_content_is_idempotent(env: Env) -> None:
    data = _onnx()
    first = await env.publish(data)
    second = await env.publish(data)
    assert second.status_code == 201 or second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["already_published"] is True
    assert len(await env.storage.list_keys("ml-models/")) == 1  # type: ignore[attr-defined]


@needs_database
async def test_same_version_with_other_content_conflicts(env: Env) -> None:
    await env.publish(_onnx("a"))
    response = await env.publish(_onnx("b"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ml_model_version_conflict"


@needs_database
@pytest.mark.parametrize(
    "data,meta_fix",
    [
        (b"", None),
        (b"not an onnx file", None),
        (_onnx(), {"version": "bad version!"}),
        (_onnx(), {"kind": "Bad Kind"}),
        (_onnx(), {"surprise": 1}),
        (_onnx(size=2 * 1024 * 1024), None),
    ],
)
async def test_invalid_uploads_are_refused(
    env: Env, data: bytes, meta_fix: dict[str, object] | None
) -> None:
    meta = _meta(data, **(meta_fix or {}))
    response = await env.publish(data, meta=meta)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "ml_model_invalid"
    assert await env.storage.list_keys("ml-models/") == []  # type: ignore[attr-defined]


@needs_database
async def test_latest_keeps_exactly_one_copy(env: Env) -> None:
    first = (await env.publish(_onnx("a"), version="1.0.0")).json()
    second = (await env.publish(_onnx("b"), version="1.1.0")).json()
    stored = await env.storage.list_keys("ml-models/")  # type: ignore[attr-defined]
    assert len(stored) == 1 and str(second["id"]) in stored[0][0]
    rows = {row["id"]: row for row in await env.listing()}
    assert rows[first["id"]]["status"] == "deleted" and rows[first["id"]]["deleted_at"]
    assert rows[second["id"]]["status"] == "ready"
    gone = await env.client.get(f"/v1/admin/ml/models/{first['id']}/download", headers=env.admin)
    assert gone.status_code == 404
    assert gone.json()["error"]["code"] == "ml_model_not_found"


@needs_database
async def test_champion_previous_version_waits_for_the_retention_window(env: Env) -> None:
    first = (await env.publish(_onnx("a"), version="1.0.0", channel="champion")).json()
    second = (await env.publish(_onnx("b"), version="1.1.0", channel="champion")).json()
    assert len(await env.storage.list_keys("ml-models/")) == 2  # type: ignore[attr-defined]
    rows = {row["id"]: row for row in await env.listing()}
    assert rows[first["id"]]["status"] == "ready" and rows[first["id"]]["superseded_at"]
    assert rows[second["id"]]["superseded_at"] is None
    # Not yet due: the sweeper keeps it.
    assert await ml_models.sweep() == 0
    await _age_superseded(first["id"], hours=73)
    assert await ml_models.sweep() == 1
    rows = {row["id"]: row for row in await env.listing()}
    assert rows[first["id"]]["status"] == "deleted"
    assert len(await env.storage.list_keys("ml-models/")) == 1  # type: ignore[attr-defined]


async def _age_superseded(model_id: str, *, hours: int) -> None:
    from sqlalchemy import update

    from app import db
    from app.models import MlModelRelease

    async with db.session_scope(staff=True) as session:
        await session.execute(
            update(MlModelRelease)
            .where(MlModelRelease.id == UUID(model_id))
            .values(superseded_at=datetime.now(UTC) - timedelta(hours=hours))
        )


@needs_database
async def test_pinned_champion_survives_the_window_and_zero_retention_deletes_at_once(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    first = (await env.publish(_onnx("a"), version="1.0.0", channel="champion")).json()
    assert (await env.action(first["id"], "pin", pinned=True)).status_code == 200
    await env.publish(_onnx("b"), version="1.1.0", channel="champion")
    await _age_superseded(first["id"], hours=1000)
    assert await ml_models.sweep() == 0
    assert (await env.action(first["id"], "pin", pinned=False)).status_code == 200
    assert await ml_models.sweep() == 1

    monkeypatch.setenv("ML_MODEL_PREV_RETENTION_HOURS", "0")
    get_settings.cache_clear()
    third = (await env.publish(_onnx("c"), version="2.0.0", channel="champion")).json()
    rows = {row["id"]: row for row in await env.listing()}
    assert [r["status"] for r in rows.values() if r["id"] != third["id"]] == ["deleted", "deleted"]
    assert len(await env.storage.list_keys("ml-models/")) == 1  # type: ignore[attr-defined]


@needs_database
async def test_publisher_key_rules(env: Env) -> None:
    data = _onnx()
    assert (await env.publish(data, headers={})).status_code == 401
    # A panel key without the scope.
    plain = await _make_key(env, cidrs=["203.0.113.0/24"], scopes=["ingest:write"])
    denied = await env.publish(data, headers={"X-API-Key": plain})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "api_key_scope_denied"
    # Address outside the allowlist.
    outside = await _make_key(env, cidrs=["198.51.100.0/24"], scopes=[ML_PUBLISH_SCOPE])
    response = await env.publish(data, headers={"X-API-Key": outside})
    assert response.status_code == 403 and response.json()["error"]["code"] == "ip_not_allowed"
    # No allowlist at all is not acceptable for a publisher.
    open_key = await _make_key(env, cidrs=[], scopes=[ML_PUBLISH_SCOPE])
    response = await env.publish(data, headers={"X-API-Key": open_key})
    assert (
        response.status_code == 403 and response.json()["error"]["code"] == "ml_publish_forbidden"
    )
    assert await env.listing() == []
    assert "ml_model.publish_denied" in await _audit_actions("ml_model.%")


@needs_database
async def test_publishing_is_closed_when_no_tenant_is_configured(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.delenv("ML_PUBLISHER_TENANT_ID")
    get_settings.cache_clear()
    response = await env.publish(_onnx())
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ml_publish_forbidden"


@needs_database
async def test_publish_is_rate_limited(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("ML_PUBLISH_PER_HOUR", "2")
    get_settings.cache_clear()
    statuses = [(await env.publish(_onnx("a"), version=f"1.0.{i}")).status_code for i in range(3)]
    assert statuses[:2] == [201, 201] and statuses[2] == 429


@needs_database
async def test_storage_failure_leaves_no_row(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(*_: object, **__: object) -> None:
        raise OSError("minio down")

    monkeypatch.setattr(env.storage, "put_path", broken)
    response = await env.publish(_onnx())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "release_file_unavailable"
    assert await env.listing() == []


@needs_database
async def test_admin_download_streams_ranges_etag_and_audit(env: Env) -> None:
    data = _onnx(size=5000)
    model = (await env.publish(data)).json()
    url = f"/v1/admin/ml/models/{model['id']}/download"
    full = await env.client.get(url, headers=env.support)
    assert full.status_code == 200 and full.content == data
    assert full.headers["etag"] == f'"{model["sha256"]}"'
    assert full.headers["accept-ranges"] == "bytes"
    part = await env.client.get(url, headers={**env.support, "Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == data[10:20]
    assert part.headers["content-range"] == f"bytes 10-19/{len(data)}"
    bad = await env.client.get(url, headers={**env.support, "Range": "bytes=999999-"})
    assert bad.status_code == 416
    anonymous = await env.client.get(url)
    assert anonymous.status_code == 401
    assert (await _audit_actions("ml_model.download")).count("ml_model.download") == 3


@needs_database
async def test_sensitive_actions_need_super_admin_and_the_password(env: Env) -> None:
    model = (await env.publish(_onnx())).json()
    for name, body in (
        ("promote", {}),
        ("rollout", {"rollout_percent": 10}),
        ("revoke", {}),
        ("pin", {"pinned": True}),
        ("delete", {}),
    ):
        url = f"/v1/admin/ml/models/{model['id']}/{name}"
        support = await env.client.post(
            url, json={"current_password": PASSWORD, **body}, headers=env.support
        )
        assert support.status_code == 403, name
        wrong = await env.client.post(
            url, json={"current_password": "wrong password", **body}, headers=env.admin
        )
        assert wrong.status_code == 401, name
    listed = await env.listing()
    assert listed[0]["channel"] == "latest" and listed[0]["status"] == "ready"


@needs_database
async def test_promote_rollout_revoke_and_delete(env: Env) -> None:
    old = (await env.publish(_onnx("a"), version="1.0.0")).json()
    assert (await env.action(old["id"], "promote")).json()["channel"] == "champion"
    new = (await env.publish(_onnx("b"), version="1.1.0")).json()
    promoted = await env.action(new["id"], "promote")
    assert promoted.status_code == 200 and promoted.json()["promoted_at"]
    rows = {row["id"]: row for row in await env.listing()}
    assert rows[old["id"]]["superseded_at"] and rows[old["id"]]["status"] == "ready"

    rollout = await env.action(new["id"], "rollout", rollout_percent=25)
    assert rollout.json()["rollout_percent"] == 25
    assert (await env.action(new["id"], "rollout", rollout_percent=101)).status_code == 422

    assert (await env.action(new["id"], "delete")).status_code == 422  # revoke first
    revoked = await env.action(new["id"], "revoke")
    assert revoked.json()["status"] == "revoked" and revoked.json()["rollout_percent"] == 0
    assert len(await env.storage.list_keys("ml-models/")) == 1  # type: ignore[attr-defined]
    assert (await env.action(new["id"], "delete")).status_code == 204
    assert new["id"] not in {row["id"] for row in await env.listing()}
    missing = await env.action(str(uuid4()), "revoke")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "ml_model_not_found"
    actions = await _audit_actions("ml_model.%")
    for name in ("promote", "rollout", "revoke", "delete"):
        assert f"ml_model.{name}" in actions


@needs_database
async def test_sweeper_collects_orphans_and_stale_uploads(env: Env) -> None:
    from sqlalchemy import update

    from app import db
    from app.models import MlModelRelease

    keep = (await env.publish(_onnx())).json()
    orphan_key = ml_models.artifact_key(uuid4(), "speaker_embedding", "9.9.9")
    await env.storage.put(orphan_key, b"x")  # type: ignore[attr-defined]
    # Fresh orphans are kept: an upload may be in flight.
    assert await ml_models.sweep() == 0
    env.storage.modified[orphan_key] = datetime.now(UTC) - timedelta(days=1)  # type: ignore[attr-defined]
    assert await ml_models.sweep() == 1
    keys = [key for key, _ in await env.storage.list_keys("ml-models/")]  # type: ignore[attr-defined]
    assert keys == [next(k for k in keys if keep["id"] in k)]

    stale = (await env.publish(_onnx("z"), version="3.0.0", channel="champion")).json()
    async with db.session_scope(staff=True) as session:
        await session.execute(
            update(MlModelRelease)
            .where(MlModelRelease.id == UUID(stale["id"]))
            .values(status="uploading", created_at=datetime.now(UTC) - timedelta(days=1))
        )
    assert await ml_models.sweep() >= 1
    rows = {row["id"]: row for row in await env.listing()}
    assert rows[stale["id"]]["status"] == "deleted"
