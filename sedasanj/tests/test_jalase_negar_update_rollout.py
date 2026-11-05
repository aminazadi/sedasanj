"""Staged rollout, minimum build, channels, anonymous install reports and the 0104/0105 chain."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

from app.errors import ERROR_STATUS
from app.services import jalase_negar_releases as apks

VERSIONS = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions"
CERT = "e7fb6bf31abdfb5d7609bc2149d983ef9b3c161ea19d312a147a8fa196952512"
INSTALL = "3f2b8c1e-5d4a-4e7b-9a10-6c2d8e4f1a77"


def _load(name: str):  # noqa: ANN202
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release(code: int, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "version_code": code,
        "min_sdk": 24,
        "abis": [],
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
        "abis": ["arm64-v8a"],
        "cert_sha256": CERT,
        "install_id": INSTALL,
    }
    args.update(device)
    return apks.select_update(rows, **args)  # type: ignore[arg-type]


def test_bucket_is_deterministic_and_in_range() -> None:
    release_id = UUID(int=7)
    first = apks.rollout_bucket(INSTALL, release_id)
    assert first == apks.rollout_bucket(INSTALL, release_id)
    assert 0 <= first < 100
    buckets = {apks.rollout_bucket(uuid4().hex, release_id) for _ in range(400)}
    assert len(buckets) > 50  # spread over the range


def test_rollout_share_roughly_matches_percent() -> None:
    release = _release(5, rollout_percent=30)
    hits = sum(_pick([release], install_id=uuid4().hex) is not None for _ in range(2000))
    assert 450 < hits < 750


def test_rollout_is_monotonic_for_one_install() -> None:
    release = _release(5)
    bucket = apks.rollout_bucket(INSTALL, release.id)
    release.rollout_percent = bucket
    assert _pick([release]) is None
    release.rollout_percent = bucket + 1
    assert _pick([release]) is not None


def test_zero_percent_and_unknown_install_are_held_back() -> None:
    assert _pick([_release(5, rollout_percent=0)]) is None
    assert _pick([_release(5, rollout_percent=50)], install_id=None) is None
    assert _pick([_release(5, rollout_percent=100)], install_id=None) is not None


def test_minimum_supported_build_bypasses_rollout_and_is_mandatory() -> None:
    release = _release(5, rollout_percent=0, min_supported_version_code=3)
    assert _pick([release], version_code=2) is release
    assert apks.is_mandatory(release, 2)
    assert _pick([release], version_code=3) is None  # not below the floor: normal rollout applies
    assert not apks.is_mandatory(release, 3)


def test_beta_builds_reach_only_beta_installs() -> None:
    rows = [_release(4), _release(6, channel="beta")]
    assert _pick(rows).version_code == 4  # type: ignore[union-attr]
    assert _pick(rows, channel="beta").version_code == 6  # type: ignore[union-attr]
    assert _pick([_release(6, channel="beta")]) is None


def test_install_id_normalisation() -> None:
    assert apks.normalize_install_id(INSTALL.upper()) == INSTALL
    assert apks.normalize_install_id("not an id!") is None
    assert apks.normalize_install_id(None) is None


# --- install-result report ---------------------------------------------------------------------


@pytest.fixture
async def client() -> httpx.AsyncClient:  # type: ignore[misc]
    from app.main import create_app

    # A fresh client address per test: the in-process limiter is shared across the session.
    address = f"203.0.113.{uuid4().int % 250 + 1}"
    transport = httpx.ASGITransport(app=create_app(), client=(address, 4000))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as http:
        yield http  # type: ignore[misc]


def _report(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "install_id": INSTALL,
        "release_id": str(uuid4()),
        "result": "installed",
        "sdk_int": 34,
        "manufacturer": "samsung",
        "silent": True,
    }
    body.update(overrides)
    return body


async def test_install_report_endpoint(client: httpx.AsyncClient) -> None:
    """One test on purpose: the app's shared limiter state is bound to a single event loop."""
    from app.metrics import jalase_negar_update_install_total as counter

    url = "/v1/jalase-negar/android/update/report"
    child = counter.labels(result="installed", error_code="none", silent="true")
    before = child._value.get()  # type: ignore[attr-defined]
    assert (await client.post(url, json=_report())).status_code == 204
    assert child._value.get() == before + 1  # type: ignore[attr-defined]

    assert (
        await client.post(url, json=_report(result="failed", error_code="boom"))
    ).status_code == 422
    assert (await client.post(url, json=_report(install_id="x; DROP"))).status_code == 422
    assert (await client.post(url, json=_report(result="failed"))).status_code == 422

    codes = [(await client.post(url, json=_report())).status_code for _ in range(32)]
    assert 429 in codes[20:]


# --- migrations and error codes ----------------------------------------------------------------


def test_rollout_migration_merges_both_0103_heads_and_is_reversible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load("0104_jalase_negar_release_rollout")
    assert module.down_revision == ("0103_account_access_help", "0103_speaker_help_content")
    for direction in ("upgrade", "downgrade"):
        statements: list[str] = []
        monkeypatch.setattr(module.op, "execute", statements.append)
        getattr(module, direction)()
        assert statements and all(not re.search(r";\s*$", s) for s in statements)
    up: list[str] = []
    monkeypatch.setattr(module.op, "execute", up.append)
    module.upgrade()
    joined = " ".join(up)
    for column in ("rollout_percent", "min_supported_version_code", "channel"):
        assert f"ADD COLUMN {column}" in joined


def test_existing_rows_stay_fully_rolled_out_on_the_stable_channel() -> None:
    module = _load("0104_jalase_negar_release_rollout")
    import inspect

    source = inspect.getsource(module.upgrade)
    assert "DEFAULT 100" in source and "DEFAULT 'stable'" in source


def test_update_error_codes_have_status_and_help_rows() -> None:
    module = _load("0105_jalase_negar_update_install_help")
    assert module.down_revision == "0104_jalase_negar_release_rollout"
    codes = {code for code, *_ in module.ERRORS}
    assert codes == {
        "update_checksum_mismatch",
        "update_downgrade_rejected",
        "update_install_blocked",
    }
    assert set(ERROR_STATUS) >= codes
    for _, title, _, cause, steps, quick in module.ERRORS:
        assert title and cause and steps and quick
