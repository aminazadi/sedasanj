from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.errors import ApiError
from app.services import module_releases as releases


def make_tar(tmp_path: Path, entry: tarfile.TarInfo | None = None) -> Path:
    path = tmp_path / "recuploader-1.6.0.tgz"
    xml = (
        b"<module><rawname>recuploader</rawname><version>1.6.0</version>"
        b"<product>issabel-recuploader</product></module>"
    )
    with tarfile.open(path, "w:gz", format=tarfile.USTAR_FORMAT) as archive:
        info = tarfile.TarInfo("recuploader/module.xml")
        info.size = len(xml)
        archive.addfile(info, io.BytesIO(xml))
        if entry:
            archive.addfile(entry, io.BytesIO(b""))
    return path


def test_artifact_product_and_format(tmp_path: Path) -> None:
    inspection = releases.inspect_artifact(make_tar(tmp_path))
    assert inspection.product == releases.PRODUCT_ISSABEL
    assert inspection.archive_format == "tgz"
    assert inspection.version == "1.6.0"
    assert releases.artifact_key(inspection.product, inspection.version).endswith(".tgz")


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]
)
def test_reject_special_entries(tmp_path: Path, kind: bytes) -> None:
    info = tarfile.TarInfo("recuploader/evil")
    info.type = kind
    info.linkname = "/etc/passwd"
    with pytest.raises(ApiError, match="unsafe"):
        releases.inspect_artifact(make_tar(tmp_path, info))


@pytest.mark.parametrize(
    "name", ["/recuploader/file", "recuploader/../file", "other/file", "recuploader/module.xml"]
)
def test_reject_paths_and_duplicates(tmp_path: Path, name: str) -> None:
    with pytest.raises(ApiError, match="unsafe"):
        releases.inspect_artifact(make_tar(tmp_path, tarfile.TarInfo(name)))


def release() -> SimpleNamespace:
    return SimpleNamespace(
        product=releases.PRODUCT_ISSABEL,
        version="1.6.0",
        version_major=1,
        version_minor=6,
        version_patch=0,
        status="published",
        channel="beta",
        min_freepbx_major=None,
        min_from_version=None,
        min_issabel_major=4,
        max_issabel_major=5,
        min_php_version="7.4.0",
        artifact_sha256="a" * 64,
        artifact_size=123,
    )


def test_host_compatibility_fails_closed() -> None:
    row = release()
    assert releases.select_update([row], "1.5.0", channel="beta")[0] is None
    for version in (None, "3", "6"):
        assert (
            releases.select_update(
                [row],
                "1.5.0",
                product=releases.PRODUCT_ISSABEL,
                issabel=version,
                channel="beta",
                php="7.4.0",
            )[0]
            is None
        )
    for version in ("4", "5"):
        assert (
            releases.select_update(
                [row],
                "1.5.0",
                product=releases.PRODUCT_ISSABEL,
                issabel=version,
                channel="beta",
                php="7.4.0",
            )[0]
            is row
        )
    assert (
        releases.select_update(
            [row],
            "1.5.0",
            product=releases.PRODUCT_ISSABEL,
            issabel="4",
            channel="beta",
            php="5.4.0",
        )[0]
        is None
    )


def test_manifest_binds_constraints() -> None:
    manifest = json.loads(releases.build_manifest(release()))
    assert manifest["product"] == releases.PRODUCT_ISSABEL
    assert manifest["archive_format"] == "tgz"
    assert manifest["min_issabel_major"] == 4
    assert manifest["max_issabel_major"] == 5
    assert manifest["min_php_version"] == "7.4.0"


def test_key_injection_keeps_product(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = make_tar(tmp_path)
    monkeypatch.setattr(releases, "public_key_b64", lambda: "test-public-key")
    releases.embed_signing_public_key(path)
    releases.embed_signing_public_key(path)
    assert releases.inspect_artifact(path).product == releases.PRODUCT_ISSABEL
    with tarfile.open(path) as archive:
        assert archive.getnames().count("recuploader/assets/release-signing.pub") == 1
        handle = archive.extractfile("recuploader/assets/release-signing.pub")
        assert handle is not None and b"test-public-key" in handle.read()


@pytest.mark.asyncio
async def test_stable_promotion_requires_lab_certification() -> None:
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from app.routers import module_updates
    from app.schemas import ModuleReleaseUpdate

    row = SimpleNamespace(product=releases.PRODUCT_ISSABEL, lab_verified=False)
    session = SimpleNamespace(get=AsyncMock(return_value=row))
    with pytest.raises(ApiError, match="lab certification"):
        await module_updates.admin_update_module_release(
            uuid4(), ModuleReleaseUpdate(channel="stable"), None, None, session
        )


def test_issabel_error_help_coverage() -> None:
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions/0071_issabel_modules.py"
    spec = importlib.util.spec_from_file_location("issabel_help_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    catalog = json.loads((path.parents[2] / "app/data/module_error_codes.json").read_text())
    assert set(migration.ERRORS).issubset({entry["code"] for entry in catalog})
