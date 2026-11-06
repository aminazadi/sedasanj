from __future__ import annotations

import gzip
import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

LEGACY_MAGIC = b"CBIBACKUP1"
MAGIC = b"CBIBACKUP2"
BLOCK = 1024 * 1024
TAG_BYTES = 16


class InvalidBackup(ValueError):
    pass


class _Readable(Protocol):
    def read(self, count: int, /) -> bytes: ...


def _copy(source: _Readable, write: Callable[[bytes], object], limit: int) -> None:
    remaining = limit
    while block := source.read(BLOCK):
        remaining -= len(block)
        if remaining < 0:
            raise InvalidBackup("backup exceeds the configured size limit")
        write(block)


class _EncryptingWriter:
    def __init__(self, output: gzip.GzipFile, encrypt: Callable[[bytes], bytes]):
        self.output = output
        self.encrypt = encrypt

    def write(self, block: bytes) -> int:
        self.output.write(self.encrypt(block))
        return len(block)

    def flush(self) -> None:
        self.output.flush()


def seal(source: Path, target: Path, secret: str, limit: int) -> tuple[str, int]:
    """Write a standard gzip containing an authenticated, gzip-compressed dump."""
    if source.stat().st_size > limit:
        raise InvalidBackup("backup exceeds the configured size limit")
    nonce = os.urandom(12)
    header = MAGIC + nonce
    key = hashlib.sha256(secret.encode()).digest()
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)
    with (
        source.open("rb") as raw,
        target.open("xb") as output,
        gzip.GzipFile(filename="", mode="wb", fileobj=output, compresslevel=0, mtime=0) as outer,
    ):
        outer.write(header)
        encrypted = _EncryptingWriter(outer, encryptor.update)
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=encrypted, compresslevel=9, mtime=0
        ) as inner:
            _copy(raw, inner.write, limit)
        outer.write(encryptor.finalize())
        outer.write(encryptor.tag)
    with target.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest(), target.stat().st_size


def wire_limit(expanded_limit: int) -> int:
    # A gzip stream carrying incompressible data can be slightly larger than its input.
    return expanded_limit + max(expanded_limit // 100, BLOCK)


def _decrypt(source: _Readable, target: Path, secret: str, limit: int, *, modern: bool) -> None:
    magic = MAGIC if modern else LEGACY_MAGIC
    header = source.read(len(magic) + 12)
    if len(header) != len(magic) + 12 or not header.startswith(magic):
        raise InvalidBackup("backup format is invalid")
    key = hashlib.sha256(secret.encode()).digest()
    decryptor = Cipher(algorithms.AES(key), modes.GCM(header[len(magic) :])).decryptor()
    if modern:
        decryptor.authenticate_additional_data(header)
    remaining = limit
    tail = b""
    with target.open("xb") as output:
        while block := source.read(BLOCK):
            remaining -= len(block)
            if remaining < 0:
                raise InvalidBackup("backup exceeds the configured size limit")
            buffered = tail + block
            tail = buffered[-TAG_BYTES:]
            output.write(decryptor.update(buffered[:-TAG_BYTES]))
        if len(tail) != TAG_BYTES:
            raise InvalidBackup("backup is truncated")
        try:
            output.write(decryptor.finalize_with_tag(tail))
        except InvalidTag as exc:
            raise InvalidBackup("backup authentication failed") from exc


def unseal(source: Path, target: Path, secret: str, limit: int) -> None:
    """Authenticate the complete input before releasing its dump to a restore process."""
    if source.stat().st_size > wire_limit(limit):
        raise InvalidBackup("backup exceeds the configured size limit")
    temporary = target.with_name(target.name + ".part")
    compressed = target.with_name(target.name + ".inner")
    try:
        with source.open("rb") as raw:
            modern = raw.read(2) == b"\x1f\x8b"
            raw.seek(0)
            if modern:
                with gzip.GzipFile(fileobj=raw) as outer:
                    _decrypt(outer, compressed, secret, wire_limit(limit), modern=True)
                with gzip.open(compressed, "rb") as inner, temporary.open("xb") as output:
                    _copy(inner, output.write, limit)
            else:
                _decrypt(raw, temporary, secret, limit + TAG_BYTES, modern=False)
        if temporary.stat().st_size == 0:
            raise InvalidBackup("backup has no database dump")
        temporary.replace(target)
    finally:
        compressed.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
