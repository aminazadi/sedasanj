from __future__ import annotations

import contextlib
import ftplib
import ipaddress
import socket
import ssl
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.errors import ApiError


@dataclass(frozen=True)
class Destination:
    protocol: str
    host: str
    port: int
    directory: str
    username: str
    password: str


def destination_error() -> ApiError:
    return ApiError(
        "org_backup_destination",
        "مقصد بک‌آپ مجاز نیست. میزبان عمومی، مسیر و نوع اتصال را بررسی کنید.",
    )


def public_address(host: str, port: int) -> str:
    try:
        addresses = list(
            dict.fromkeys(
                item[4][0]
                for item in socket.getaddrinfo(
                    host,
                    port,
                    type=socket.SOCK_STREAM,
                )
            )
        )
    except socket.gaierror as exc:
        raise ApiError(
            "org_backup_ftp_failed",
            "میزبان مقصد پیدا نشد. نام میزبان و تنظیمات شبکه را بررسی کنید.",
            retryable=True,
        ) from exc
    if not addresses:
        raise destination_error()
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise destination_error()
    return str(addresses[0])


def _passive_peer(client: ftplib.FTP) -> tuple[str, int]:
    # PASV may advertise a different IP. Always use the already pinned control peer.
    if client.sock is None:
        raise ConnectionError("FTP control connection is closed")
    peer = client.sock.getpeername()
    if client.af == socket.AF_INET:
        _, port = ftplib.parse227(client.sendcmd("PASV"))
    else:
        _, port = ftplib.parse229(client.sendcmd("EPSV"), peer)
    if not 1024 <= port <= 65535:
        raise destination_error()
    return str(peer[0]), port


class PublicFTP(ftplib.FTP):
    makepasv = _passive_peer


class PublicFTPS(ftplib.FTP_TLS):
    makepasv = _passive_peer


@contextlib.contextmanager
def connect(destination: Destination, *, allow_plain: bool) -> Iterator[ftplib.FTP]:
    if destination.protocol not in {"ftps", "ftp"} or (
        destination.protocol == "ftp" and not allow_plain
    ):
        raise destination_error()
    if any(
        ord(char) < 32 or ord(char) == 127
        for field in (
            destination.host,
            destination.directory,
            destination.username,
            destination.password,
        )
        for char in field
    ):
        raise destination_error()
    if any(part == ".." for part in destination.directory.split("/")):
        raise destination_error()
    address = public_address(destination.host, destination.port)
    client: ftplib.FTP
    if destination.protocol == "ftps":
        client = PublicFTPS(context=ssl.create_default_context(), timeout=20)
    else:
        client = PublicFTP(timeout=20)
    try:
        client.connect(address, destination.port)
        client.host = destination.host
        client.login(destination.username, destination.password)
        if isinstance(client, ftplib.FTP_TLS):
            client.prot_p()
        client.set_pasv(True)
        client.cwd(destination.directory)
        yield client
    except ssl.SSLError as exc:
        raise ApiError(
            "org_backup_ftp_failed",
            "اتصال امن برقرار نشد. گواهی و پشتیبانی از FTPS صریح را بررسی کنید.",
        ) from exc
    except ftplib.all_errors as exc:
        raise ApiError(
            "org_backup_ftp_failed",
            "ارسال به مقصد انجام نشد. دسترسی نوشتن، مسیر و اتصال سرور را بررسی کنید.",
            retryable=isinstance(exc, (OSError, EOFError, ftplib.error_temp)),
        ) from exc
    finally:
        client.close()


def _publish(client: ftplib.FTP, path: Path, filename: str, timeout: float) -> None:
    temporary = f".{filename}.partial"
    deadline = time.monotonic() + timeout

    def check_deadline(_: bytes) -> None:
        if time.monotonic() >= deadline:
            raise TimeoutError("FTP transfer exceeded its deadline")

    try:
        try:
            client.voidcmd("TYPE I")
            published_size = client.size(filename)
        except ftplib.error_perm:
            published_size = None
        if published_size == path.stat().st_size:
            import hashlib

            published_hash = hashlib.sha256()

            def verify(block: bytes) -> None:
                check_deadline(block)
                published_hash.update(block)

            client.retrbinary(f"RETR {filename}", verify)
            with path.open("rb") as existing:
                if published_hash.digest() == hashlib.file_digest(existing, "sha256").digest():
                    return
        with path.open("rb") as payload:
            client.storbinary(f"STOR {temporary}", payload, 256 * 1024, check_deadline)
        if client.size(temporary) != path.stat().st_size:
            raise OSError("FTP transfer size mismatch")
        client.rename(temporary, filename)
    except BaseException:
        with contextlib.suppress(*ftplib.all_errors):
            client.delete(temporary)
        raise


def transfer(
    destination: Destination,
    path: Path,
    filename: str,
    *,
    allow_plain: bool,
    timeout: float,
) -> None:
    with connect(destination, allow_plain=allow_plain) as client:
        _publish(client, path, filename, timeout)


def test_destination(destination: Destination, path: Path, *, allow_plain: bool) -> None:
    with connect(destination, allow_plain=allow_plain) as client:
        filename = f".sedasanj-test-{uuid4().hex}"
        _publish(client, path, filename, 20)
        client.delete(filename)
