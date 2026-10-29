from __future__ import annotations

import base64
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.config import get_settings
from app.errors import ApiError
from app.services import module_releases as releases

MODULE_XML = "<module><rawname>{rawname}</rawname><version>{version}</version></module>"


def _zip(tmp_path: Path, entries: dict[str, bytes], name: str = "module.zip") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for entry, body in entries.items():
            archive.writestr(entry, body)
    return path


def _module_zip(tmp_path: Path, version: str = "1.3.0", rawname: str = "recuploader") -> Path:
    return _zip(
        tmp_path,
        {
            "recuploader/module.xml": MODULE_XML.format(rawname=rawname, version=version).encode(),
            "recuploader/Recuploader.class.php": b"<?php\n",
        },
    )


def _release(version: str, **overrides: object) -> SimpleNamespace:
    major, minor, patch = releases.parse_version(version)
    values: dict[str, object] = {
        "version": version,
        "version_major": major,
        "version_minor": minor,
        "version_patch": patch,
        "status": "published",
        "channel": "stable",
        "min_freepbx_major": None,
        "min_from_version": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_inspect_zip_reads_version_and_digest(tmp_path: Path) -> None:
    path = _module_zip(tmp_path)
    inspection = releases.inspect_zip(path)
    assert inspection.version == "1.3.0"
    assert inspection.rawname == "recuploader"
    assert len(inspection.sha256) == 64
    assert inspection.size == path.stat().st_size


def test_inspect_zip_rejects_wrong_rawname(tmp_path: Path) -> None:
    with pytest.raises(ApiError, match="rawname"):
        releases.inspect_zip(_module_zip(tmp_path, rawname="other"))


def test_inspect_zip_rejects_bad_version(tmp_path: Path) -> None:
    with pytest.raises(ApiError, match="version"):
        releases.inspect_zip(_module_zip(tmp_path, version="1.3"))


@pytest.mark.parametrize(
    "entry", ["recuploader/../../etc/passwd", "/recuploader/x", "other/module.xml"]
)
def test_inspect_zip_rejects_unsafe_paths(tmp_path: Path, entry: str) -> None:
    path = _zip(
        tmp_path,
        {
            "recuploader/module.xml": MODULE_XML.format(
                rawname="recuploader", version="1.0.0"
            ).encode(),
            entry: b"x",
        },
    )
    with pytest.raises(ApiError) as caught:
        releases.inspect_zip(path)
    assert caught.value.code == "archive_unsafe"


def test_inspect_zip_rejects_symlinks(tmp_path: Path) -> None:
    path = tmp_path / "link.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "recuploader/module.xml", MODULE_XML.format(rawname="recuploader", version="1.0.0")
        )
        link = zipfile.ZipInfo("recuploader/evil")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "/etc/shadow")
    with pytest.raises(ApiError, match="symlink"):
        releases.inspect_zip(path)


def test_inspect_zip_rejects_non_zip(tmp_path: Path) -> None:
    path = tmp_path / "bad.zip"
    path.write_bytes(b"not a zip")
    with pytest.raises(ApiError) as caught:
        releases.inspect_zip(path)
    assert caught.value.code == "unsupported_archive"


def test_signature_verifies_with_published_public_key(monkeypatch: pytest.MonkeyPatch) -> None:
    seed = base64.b64encode(bytes(range(32))).decode()
    monkeypatch.setattr(get_settings(), "module_release_signing_key", seed)
    digest = "a" * 64
    signature = base64.b64decode(releases.sign_digest(digest))
    public = Ed25519PublicKey.from_public_bytes(base64.b64decode(releases.public_key_b64()))
    public.verify(signature, digest.encode("ascii"))


def test_signing_requires_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "module_release_signing_key", None)
    monkeypatch.setattr(get_settings(), "module_release_signing_key_file", None)
    with pytest.raises(ApiError, match="SIGNING_KEY"):
        releases.sign_digest("a" * 64)


def test_signing_key_is_generated_once_and_persisted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key_file = tmp_path / "signing" / "private.seed"
    monkeypatch.setattr(get_settings(), "module_release_signing_key", None)
    monkeypatch.setattr(get_settings(), "module_release_signing_key_file", str(key_file))

    first_public_key = releases.public_key_b64()
    second_public_key = releases.public_key_b64()

    assert first_public_key == second_public_key
    assert len(key_file.read_bytes()) == 32
    assert key_file.stat().st_mode & 0o777 == 0o600


def test_published_archive_contains_matching_public_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seed = base64.b64encode(bytes(range(32))).decode()
    monkeypatch.setattr(get_settings(), "module_release_signing_key", seed)
    path = _module_zip(tmp_path)

    releases.embed_signing_public_key(path)
    inspection = releases.inspect_zip(path)
    signature = base64.b64decode(releases.sign_digest(inspection.sha256))

    with zipfile.ZipFile(path) as archive:
        public_key_file = archive.read("recuploader/assets/release-signing.pub").decode()
    public_key_b64 = [
        line for line in public_key_file.splitlines() if line and not line.startswith("#")
    ][0]
    assert public_key_b64 == releases.public_key_b64()
    public = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
    public.verify(signature, inspection.sha256.encode("ascii"))


def test_sanitize_strips_scripts_handlers_and_bad_links() -> None:
    html, plain = releases.sanitize_changelog(
        '<h2 style="color:red">امکانات جدید</h2><script>alert(1)</script>'
        '<p onclick="x()">متن <a href="javascript:alert(1)">بد</a> '
        '<a href="https://sedasanj.ir">خوب</a></p><img src=x onerror=alert(1)>'
        '<pre class="language-bash"><code>fwconsole reload</code></pre><ul><li>یک'
    )
    assert "script" not in html and "alert" not in html
    assert "onclick" not in html and "style" not in html and "<img" not in html
    assert "javascript" not in html and "بد</a>" in html
    assert 'href="https://sedasanj.ir"' in html and 'rel="noopener noreferrer"' in html
    assert '<pre class="language-bash">' in html
    assert html.endswith("</li></ul>")
    assert "امکانات جدید" in plain and "fwconsole reload" in plain


def test_sanitize_escapes_text() -> None:
    html, _ = releases.sanitize_changelog("<p>&lt;b&gt;not bold&lt;/b&gt;</p>")
    assert html == "<p>&lt;b&gt;not bold&lt;/b&gt;</p>"


def test_select_update_returns_newest_and_every_step_between() -> None:
    rows = [_release(v) for v in ("1.2.1", "1.3.0", "1.3.1", "1.4.0")]
    latest, changelog = releases.select_update(rows, "1.2.1")
    assert latest is not None and latest.version == "1.4.0"
    assert [row.version for row in changelog] == ["1.4.0", "1.3.1", "1.3.0"]


def test_select_update_none_when_current_is_newest() -> None:
    assert releases.select_update([_release("1.3.0")], "1.3.0") == (None, [])
    assert releases.select_update([_release("1.3.0")], "2.0.0") == (None, [])


def test_select_update_ignores_drafts_revoked_and_beta() -> None:
    rows = [
        _release("1.3.0"),
        _release("1.4.0", status="draft"),
        _release("1.5.0", status="revoked"),
        _release("1.6.0", channel="beta"),
    ]
    latest, _ = releases.select_update(rows, "1.2.0")
    assert latest is not None and latest.version == "1.3.0"
    beta, _ = releases.select_update(rows, "1.2.0", channel="beta")
    assert beta is not None and beta.version == "1.6.0"


def test_select_update_respects_freepbx_and_upgrade_floor() -> None:
    rows = [
        _release("1.3.0"),
        _release("1.4.0", min_freepbx_major=17),
        _release("2.0.0", min_from_version="1.4.0"),
    ]
    latest, changelog = releases.select_update(rows, "1.2.0", freepbx="16.0.40")
    assert latest is not None and latest.version == "1.3.0"
    assert [row.version for row in changelog] == ["1.3.0"]
    latest, _ = releases.select_update(rows, "1.2.0", freepbx="17.0.1")
    assert latest is not None and latest.version == "1.4.0"
    latest, _ = releases.select_update(rows, "1.4.0", freepbx="17.0.1")
    assert latest is not None and latest.version == "2.0.0"


def test_manifest_is_canonical_signed_and_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64
    import json
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from app.config import get_settings
    from app.services import module_releases as releases

    seed = base64.b64encode(bytes(range(32))).decode()
    monkeypatch.setattr(get_settings(), "module_release_signing_key", seed)
    release = SimpleNamespace(
        product="freepbx-recuploader",
        version="1.4.0",
        artifact_sha256="a" * 64,
        artifact_size=1234,
        channel="stable",
        min_freepbx_major=15,
        min_from_version=None,
    )
    now = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
    manifest = releases.build_manifest(release, now=now)  # type: ignore[arg-type]
    data = json.loads(manifest)
    assert data["version"] == "1.4.0" and data["sha256"] == "a" * 64 and data["size"] == 1234
    assert (
        data["issued_at"] == "2026-10-29T12:00:00Z" and data["expires_at"] == "2026-11-05T12:00:00Z"
    )
    assert manifest == releases.build_manifest(release, now=now)  # type: ignore[arg-type]
    assert "\n" not in manifest

    public = Ed25519PublicKey.from_public_bytes(base64.b64decode(releases.public_key_b64()))
    signature = base64.b64decode(releases.sign_manifest(manifest))
    public.verify(signature, releases.MANIFEST_DOMAIN + manifest.encode("ascii"))
    # A digest signature must not verify as a manifest signature (domain separation).
    from cryptography.exceptions import InvalidSignature

    digest_signature = base64.b64decode(releases.sign_digest("a" * 64))
    with pytest.raises(InvalidSignature):
        public.verify(digest_signature, releases.MANIFEST_DOMAIN + manifest.encode("ascii"))


def test_publish_and_revoke_require_password_proof() -> None:
    from app.routers.module_updates import router

    wanted = {"admin_publish_module_release", "admin_revoke_module_release"}
    found = set()
    for route in router.routes:
        endpoint = getattr(route, "endpoint", None)
        if getattr(endpoint, "__name__", "") in wanted:
            found.add(endpoint.__name__)
            body_fields = [f.name for f in route.dependant.body_params]  # type: ignore[attr-defined]
            assert body_fields, f"{endpoint.__name__} must take a StaffSensitiveAction body"
    assert found == wanted


def _release(version: str, **kw):
    from types import SimpleNamespace

    major, minor, patch = (int(x) for x in version.split("."))
    base = dict(
        version=version,
        version_major=major,
        version_minor=minor,
        version_patch=patch,
        status="published",
        channel="stable",
        min_freepbx_major=None,
        max_freepbx_major=None,
        min_php_version=None,
        min_from_version=None,
    )
    return SimpleNamespace(**{**base, **kw})


def test_compatibility_bounds_fail_closed_and_respect_php_floor() -> None:
    from app.services.module_releases import select_update

    limited = _release("1.4.0", min_freepbx_major=16, max_freepbx_major=17, min_php_version="7.4")
    assert select_update([limited], "1.3.9", freepbx="16.0.40", php="7.4.33")[0] is limited
    assert select_update([limited], "1.3.9", freepbx="17.0.1", php="8.2.1")[0] is limited
    assert select_update([limited], "1.3.9", freepbx="15.0.17", php="7.4.33")[0] is None  # too old
    assert select_update([limited], "1.3.9", freepbx="18.0.1", php="8.2.1")[0] is None  # too new
    assert select_update([limited], "1.3.9", freepbx=None, php="7.4.33")[0] is None  # unknown host
    assert select_update([limited], "1.3.9", freepbx="16.0.40", php="7.3.2")[0] is None  # PHP floor
    assert select_update([limited], "1.3.9", freepbx="16.0.40", php=None)[0] is None
    # An older, compatible release is offered when the newest one does not fit.
    older = _release("1.3.10")
    assert select_update([limited, older], "1.3.9", freepbx="15.0.17", php="7.4.33")[0] is older
