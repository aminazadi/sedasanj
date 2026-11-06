from __future__ import annotations

import gzip
import hashlib
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import tenant_backup_format
from app.services.tenant_backups import _encrypt_file

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup_bundle.py"
spec = importlib.util.spec_from_file_location("backup_bundle", SCRIPT)
assert spec is not None and spec.loader is not None
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


@pytest.mark.parametrize("modern", [False, True])
def test_tenant_backup_round_trip(tmp_path: Path, modern: bool) -> None:
    source, archive, restored = (tmp_path / name for name in ("dump", "archive", "restored"))
    data = b"synthetic PostgreSQL dump\n" * 8192
    source.write_bytes(data)
    if modern:
        checksum, size = tenant_backup_format.seal(source, archive, "test-secret", len(data))
        assert gzip.decompress(archive.read_bytes()).startswith(tenant_backup_format.MAGIC)
        assert size < len(data) // 10
    else:
        checksum, size = _encrypt_file(source, archive, "test-secret")
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == checksum
    assert archive.stat().st_size == size
    tenant_backup_format.unseal(archive, restored, "test-secret", len(data))
    assert restored.read_bytes() == data


@pytest.mark.parametrize("failure", ["wrong-key", "corrupt", "truncated", "oversized"])
def test_tenant_backup_never_releases_invalid_dump(tmp_path: Path, failure: str) -> None:
    source, archive, restored = (tmp_path / name for name in ("dump", "archive", "restored"))
    source.write_bytes(b"payload" * 4096)
    limit = source.stat().st_size
    key = "test-secret"
    tenant_backup_format.seal(source, archive, key, limit)
    if failure == "wrong-key":
        key = "wrong-secret"
    elif failure == "corrupt":
        envelope = bytearray(gzip.decompress(archive.read_bytes()))
        envelope[-1] ^= 1
        archive.write_bytes(gzip.compress(envelope, compresslevel=0))
    elif failure == "truncated":
        archive.write_bytes(archive.read_bytes()[:-3])
    else:
        limit = 1024
    with pytest.raises((tenant_backup_format.InvalidBackup, EOFError, gzip.BadGzipFile)):
        tenant_backup_format.unseal(archive, restored, key, limit)
    assert not restored.exists()
    assert not list(tmp_path.glob("restored.*"))


@pytest.mark.skipif(
    not all(shutil.which(program) for program in ("age", "age-keygen", "openssl")),
    reason="requires the age and OpenSSL command-line tools",
)
def test_signed_dr_bundle_round_trip_and_dedup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key, public, identity, recipients = (
        tmp_path / name for name in ("private.pem", "public.pem", "identity", "recipients")
    )
    for command in (
        ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)],
        ["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(public)],
        ["age-keygen", "-o", str(identity)],
    ):
        subprocess.run(command, check=True, capture_output=True)
    recipients.write_bytes(subprocess.check_output(["age-keygen", "-y", str(identity)]))
    monkeypatch.setenv("BACKUP_SIGNING_KEY_FILE", str(key))
    monkeypatch.setenv("BACKUP_VERIFY_KEY_FILE", str(public))
    monkeypatch.setenv("BACKUP_AGE_IDENTITY_FILE", str(identity))
    monkeypatch.setenv("BACKUP_AGE_RECIPIENTS_FILE", str(recipients))
    src, root = tmp_path / "capture", tmp_path / "root"
    for name, data in {
        "MANIFEST": b"example",
        "cbi.dump": b"test control database",
        "tenants/cbi_tenant_example.dump": b"test tenant database",
        "secrets/env": b"test deployment settings",
        "objects/sample.wav": b"synthetic WAV" * 1000,
    }.items():
        path = src / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    first = bundle.capture(src, root, "20261006T000000Z")
    second = bundle.capture(src, root, "20261007T000000Z")
    assert len(list((root / "blobs").glob("*/*.age"))) == 5
    for path in (first / "payloads").glob("*.age"):
        assert (second / "payloads" / path.name).stat().st_ino == path.stat().st_ino

    backup, restored = tmp_path / "test.gzip", tmp_path / "restored"
    bundle.export(second, backup)
    bundle.unpack(backup, restored, 2 * 1024**2)
    for path in src.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (restored / path.relative_to(src)).read_bytes()

    damaged = tmp_path / "damaged.gzip"
    damaged.write_bytes(backup.read_bytes()[:-1])
    bad_restore = tmp_path / "bad-restore"
    with pytest.raises((bundle.InvalidBundle, EOFError, gzip.BadGzipFile)):
        bundle.unpack(damaged, bad_restore, 2 * 1024**2)
    assert not bad_restore.exists()

    signed_manifest = second / "manifest.json"
    signed_manifest.write_bytes(signed_manifest.read_bytes() + b" ")
    with pytest.raises(bundle.InvalidBundle, match="openssl failed"):
        bundle.export(second, tmp_path / "unsigned.gzip")

    bundle.prune(root, 0, 1)
    assert not first.exists() and second.is_dir()
    assert len(list((root / "blobs").glob("*/*.age"))) == 5


@pytest.mark.parametrize("name", ["../escape", "/absolute", "nested/../escape", "a\\b", "a//b"])
def test_dr_rejects_unsafe_manifest_paths(name: str) -> None:
    with pytest.raises(bundle.InvalidBundle, match="invalid snapshot member name"):
        bundle.safe_name(name)
