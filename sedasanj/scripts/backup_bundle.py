#!/usr/bin/env python3
"""Build, export and verify signed SedaSanj disaster-recovery generations."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Protocol

BLOCK = 1024 * 1024
MAX_MANIFEST = 64 * BLOCK
MAX_SIGNATURE = 128
HASH = re.compile(r"[0-9a-f]{64}")


class InvalidBundle(ValueError):
    pass


class BundleMember(tarfile.TarInfo):
    @classmethod
    def frombuf(cls, buf: bytes | bytearray, encoding: str, errors: str) -> BundleMember:
        member = super().frombuf(buf, encoding, errors)
        if member.type != tarfile.REGTYPE:
            raise InvalidBundle("unsupported snapshot archive member")
        return member


class Reader(Protocol):
    def read(self, count: int, /) -> bytes: ...


class Writer(Protocol):
    def write(self, block: bytes, /) -> object: ...


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise InvalidBundle(f"set {name} before running this operation")
    return str(Path(value).resolve(strict=True))


def safe_name(name: str) -> str:
    relative = PurePosixPath(name)
    if (
        not relative.parts
        or relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != name
        or "\\" in name
        or any(ord(char) < 32 for char in name)
    ):
        raise InvalidBundle("invalid snapshot member name")
    return name


def copy_exact(source: Reader, target: Writer, size: int) -> None:
    while size:
        block = source.read(min(size, BLOCK))
        if not block:
            raise InvalidBundle("snapshot member is truncated")
        target.write(block)
        size -= len(block)
    if source.read(1):
        raise InvalidBundle("snapshot member exceeds its declared size")


def run_crypto(args: list[str]) -> None:
    try:
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InvalidBundle(f"{args[0]} failed; check backup keys and file integrity") from exc


def sign(manifest: Path, signature: Path) -> None:
    run_crypto(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-rawin",
            "-inkey",
            required_env("BACKUP_SIGNING_KEY_FILE"),
            "-in",
            str(manifest),
            "-out",
            str(signature),
        ]
    )


def verify_signature(manifest: Path, signature: Path) -> None:
    run_crypto(
        [
            "openssl",
            "pkeyutl",
            "-verify",
            "-rawin",
            "-pubin",
            "-inkey",
            required_env("BACKUP_VERIFY_KEY_FILE"),
            "-in",
            str(manifest),
            "-sigfile",
            str(signature),
        ]
    )


def seal(source: Path, target: Path, recipients: str, size: int) -> None:
    with target.open("xb") as output:
        with subprocess.Popen(
            ["age", "-R", recipients],
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.DEVNULL,
        ) as process:
            assert process.stdin is not None
            with (
                source.open("rb") as raw,
                gzip.GzipFile(
                    filename="", fileobj=process.stdin, mode="wb", compresslevel=9, mtime=0
                ) as compressed,
            ):
                copy_exact(raw, compressed, size)
            process.stdin.close()
            if process.wait():
                raise InvalidBundle("age encryption failed; check the configured recipient")
        output.flush()
        os.fsync(output.fileno())


def unseal(source: Path, target: Path, size: int, identity: str) -> None:
    with subprocess.Popen(
        ["age", "-d", "-i", identity, str(source)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        assert process.stdout is not None
        try:
            with gzip.GzipFile(fileobj=process.stdout) as raw, target.open("xb") as output:
                copy_exact(raw, output, size)
            if process.wait():
                raise InvalidBundle("age authentication failed; check the recovery identity")
        finally:
            if process.poll() is None:
                process.kill()


def _blob(
    source: Path, cache: Path, recipients: str, raw_hash: str, size: int, workspace: Path
) -> tuple[Path, str]:
    blob = cache / f"{raw_hash}.age"
    checksum = blob.with_suffix(".sha256")
    if blob.is_file() and checksum.is_file():
        actual = digest(blob)
        if actual == checksum.read_text().strip():
            return blob, actual
    temp_blob = workspace / "new.age"
    seal(source, temp_blob, recipients, size)
    encrypted_hash = digest(temp_blob)
    temp_checksum = workspace / "new.sha256"
    temp_checksum.write_text(encrypted_hash + "\n")
    temp_blob.replace(blob)
    temp_checksum.replace(checksum)
    return blob, encrypted_hash


def capture(source: Path, root: Path, stamp: str) -> Path:
    if not re.fullmatch(r"\d{8}T\d{6}Z", stamp):
        raise InvalidBundle("invalid snapshot timestamp")
    if not all((source / name).is_file() for name in ("cbi.dump", "MANIFEST", "secrets/env")):
        raise InvalidBundle("capture is missing its database, metadata or recovery settings")
    recipients = required_env("BACKUP_AGE_RECIPIENTS_FILE")
    cache = root / "blobs" / digest(Path(recipients))
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    generations = root / "generations"
    generations.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = generations / stamp
    if target.exists():
        raise InvalidBundle("snapshot generation already exists")
    with tempfile.TemporaryDirectory(prefix=".capture-", dir=generations) as temporary:
        workspace = Path(temporary)
        generation = workspace / "generation"
        generation.mkdir(mode=0o700)
        payloads = generation / "payloads"
        payloads.mkdir(mode=0o700)
        entries = []
        for path in sorted(source.rglob("*")):
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise InvalidBundle("snapshot contains an unsupported file")
            if path.is_dir():
                continue
            name = safe_name(path.relative_to(source).as_posix())
            size, raw_hash = path.stat().st_size, digest(path)
            blob, encrypted_hash = _blob(path, cache, recipients, raw_hash, size, workspace)
            encrypted_path = payloads / f"{encrypted_hash}.age"
            if not encrypted_path.exists():
                os.link(blob, encrypted_path)
            entries.append([name, size, raw_hash, encrypted_hash, blob.stat().st_size])

        manifest = generation / "manifest.json"
        manifest.write_text(
            json.dumps({"version": 2, "stamp": stamp, "entries": entries}, separators=(",", ":"))
        )
        if manifest.stat().st_size > MAX_MANIFEST:
            raise InvalidBundle("snapshot inventory exceeds the manifest limit")
        sign(manifest, generation / "manifest.sig")
        generation.rename(target)
    return target


def export(generation: Path, destination: Path) -> None:
    if destination.exists() or destination.suffix != ".gzip":
        raise InvalidBundle("choose a new destination ending in .gzip")
    manifest, signature = generation / "manifest.json", generation / "manifest.sig"
    verify_signature(manifest, signature)
    payloads = _manifest(manifest, 2 * 1024**4)
    with tempfile.TemporaryDirectory(prefix=".export-", dir=destination.parent) as temporary:
        partial = Path(temporary) / "bundle"
        with (
            partial.open("xb") as output,
            gzip.GzipFile(
                filename="", fileobj=output, mode="wb", compresslevel=0, mtime=0
            ) as outer,
            tarfile.open(fileobj=outer, mode="w|", format=tarfile.GNU_FORMAT) as tar,
        ):
            for name in ("manifest.json", "manifest.sig"):
                tar.add(generation / name, arcname=name, recursive=False)
            for name in sorted(payloads):
                path = generation / name
                if path.is_symlink() or digest(path) != path.stem:
                    raise InvalidBundle("snapshot ciphertext checksum differs")
                tar.add(path, arcname=name, recursive=False)
        os.link(partial, destination)


def _entry(tar: tarfile.TarFile, member: tarfile.TarInfo, target: Path, limit: int) -> None:
    if not member.isfile() or member.size > limit:
        raise InvalidBundle("invalid snapshot member type or size")
    stream = tar.extractfile(member)
    if stream is None:
        raise InvalidBundle("snapshot member could not be read")
    with stream, target.open("xb") as output:
        copy_exact(stream, output, member.size)


def _manifest(path: Path, limit: int) -> dict[str, list[tuple[str, int, str, int]]]:
    if path.stat().st_size > MAX_MANIFEST:
        raise InvalidBundle("snapshot inventory exceeds the manifest limit")
    document = json.loads(path.read_bytes())
    if document["version"] != 2:
        raise InvalidBundle("unsupported snapshot format")
    names = set()
    payloads: dict[str, list[tuple[str, int, str, int]]] = {}
    total = 0
    for name, size, raw_hash, encrypted_hash, sealed_size in document["entries"]:
        safe_name(name)
        if (
            name in names
            or type(size) is not int
            or size < 0
            or type(sealed_size) is not int
            or not 0 < sealed_size <= limit
            or not HASH.fullmatch(raw_hash)
            or not HASH.fullmatch(encrypted_hash)
        ):
            raise InvalidBundle("invalid snapshot inventory")
        names.add(name)
        total += size
        if total > limit:
            raise InvalidBundle("snapshot exceeds the restore size limit")
        payloads.setdefault(f"payloads/{encrypted_hash}.age", []).append(
            (name, size, raw_hash, sealed_size)
        )
    if "cbi.dump" not in names or "MANIFEST" not in names:
        raise InvalidBundle("snapshot is missing its control database or metadata")
    return payloads


def unpack(archive: Path, destination: Path, limit: int) -> None:
    identity = required_env("BACKUP_AGE_IDENTITY_FILE")
    if destination.exists() or archive.stat().st_size > limit + max(limit // 20, MAX_MANIFEST):
        raise InvalidBundle("choose an empty restore destination and check the restore limit")
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=destination.parent) as temporary:
        workspace = Path(temporary)
        stage = workspace / "stage"
        stage.mkdir(mode=0o700)
        with (
            gzip.open(archive, "rb") as outer,
            tarfile.open(fileobj=outer, mode="r|", tarinfo=BundleMember) as tar,
        ):
            for name, max_bytes in (
                ("manifest.json", MAX_MANIFEST),
                ("manifest.sig", MAX_SIGNATURE),
            ):
                member = tar.next()
                if member is None or member.name != name:
                    raise InvalidBundle("snapshot is missing its signed inventory")
                _entry(tar, member, workspace / name, max_bytes)
            verify_signature(workspace / "manifest.json", workspace / "manifest.sig")
            payloads = _manifest(workspace / "manifest.json", limit)
            expanded = sum(item[1] for items in payloads.values() for item in items)
            largest = max(items[0][3] for items in payloads.values())
            if shutil.disk_usage(workspace).free < expanded + largest:
                raise InvalidBundle("free more staging disk before restoring the snapshot")
            while (member := tar.next()) is not None:
                items = payloads.pop(member.name, None)
                if not items or any(item[3] != member.size for item in items):
                    raise InvalidBundle("unexpected, duplicate or invalid snapshot payload")
                encrypted = workspace / "member.age"
                _entry(tar, member, encrypted, member.size)
                if digest(encrypted) != Path(member.name).stem:
                    raise InvalidBundle("snapshot ciphertext checksum differs")
                first: Path | None = None
                for name, size, raw_hash, _ in items:
                    output = stage / name
                    output.parent.mkdir(parents=True, exist_ok=True)
                    if first is None:
                        unseal(encrypted, output, size, identity)
                        first = output
                    else:
                        shutil.copyfile(first, output)
                    if digest(output) != raw_hash:
                        raise InvalidBundle("snapshot content checksum differs")
                encrypted.unlink()
            if payloads:
                raise InvalidBundle("snapshot payloads are missing")
            if len(outer.read(10241)) > 10240:
                raise InvalidBundle("unexpected data after snapshot archive")
        stage.rename(destination)


def prune(root: Path, retention_days: int, keep_last: int) -> None:
    if retention_days < 0 or keep_last < 1:
        raise InvalidBundle("retain at least one complete generation")
    generations = sorted(
        (
            path
            for path in (root / "generations").iterdir()
            if re.fullmatch(r"\d{8}T\d{6}Z", path.name)
            and path.is_dir()
            and (path / "manifest.sig").is_file()
        ),
        reverse=True,
    )
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    for generation in generations[keep_last:]:
        created = datetime.strptime(generation.name, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if created < cutoff:
            shutil.rmtree(generation)
    for blob in (root / "blobs").glob("*/*.age"):
        if blob.stat().st_nlink == 1:
            blob.unlink()
            blob.with_suffix(".sha256").unlink(missing_ok=True)


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="operation", required=True)
    capture_parser = operations.add_parser("capture")
    capture_parser.add_argument("source", type=Path)
    capture_parser.add_argument("root", type=Path)
    capture_parser.add_argument("stamp")
    export_parser = operations.add_parser("export")
    export_parser.add_argument("generation", type=Path)
    export_parser.add_argument("destination", type=Path)
    unpack_parser = operations.add_parser("unpack")
    unpack_parser.add_argument("archive", type=Path)
    unpack_parser.add_argument("destination", type=Path)
    unpack_parser.add_argument("--limit", type=int, default=2 * 1024**4)
    prune_parser = operations.add_parser("prune")
    prune_parser.add_argument("root", type=Path)
    prune_parser.add_argument("retention_days", type=int)
    prune_parser.add_argument("keep_last", type=int)
    args = parser.parse_args()
    try:
        if args.operation == "capture":
            print(capture(args.source, args.root, args.stamp))
        elif args.operation == "export":
            export(args.generation, args.destination)
        elif args.operation == "unpack":
            unpack(args.archive, args.destination, args.limit)
        else:
            prune(args.root, args.retention_days, args.keep_last)
    except (OSError, ValueError, TypeError, KeyError, tarfile.TarError, EOFError) as exc:
        message = (
            str(exc) if isinstance(exc, InvalidBundle) else "check backup files and available disk"
        )
        parser.exit(1, f"Backup operation failed: {message}\n")


if __name__ == "__main__":
    main()
