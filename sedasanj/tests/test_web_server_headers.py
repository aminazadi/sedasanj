"""The static web server must send the security headers (WSTG-CONF-07, CLNT-09)."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1] / "deploy" / "web-server.mjs"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start(tmp_path: Path, app: str, **env: str) -> Iterator[int]:
    (tmp_path / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    port = _free_port()
    process = subprocess.Popen(  # noqa: S603
        ["node", str(SERVER)],  # noqa: S607
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "STATIC_ROOT": str(tmp_path),
            "PORT": str(port),
            "WEB_APP": app,
            **env,
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        yield port
    finally:
        process.terminate()
        process.wait(timeout=5)


def _headers(port: int, path: str = "/") -> dict[str, str]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:  # noqa: S310
        return {key.lower(): value for key, value in response.headers.items()}


@pytest.fixture()
def admin_port(tmp_path: Path) -> Iterator[int]:
    yield from _start(tmp_path, "admin")


@pytest.fixture()
def client_port(tmp_path: Path) -> Iterator[int]:
    yield from _start(tmp_path, "client", CSP_MEDIA_ORIGINS="https://audio.example.com")


def test_admin_headers_forbid_framing_and_inline_scripts(admin_port: int) -> None:
    headers = _headers(admin_port)
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["strict-transport-security"].startswith("max-age=")
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
    csp = headers["content-security-policy"]
    assert "script-src 'self';" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "microphone=()" in headers["permissions-policy"]


def test_client_csp_allows_audio_origin_and_microphone(client_port: int) -> None:
    headers = _headers(client_port)
    csp = headers["content-security-policy"]
    assert "media-src 'self' blob: https://audio.example.com" in csp
    assert "connect-src 'self'" in csp
    assert "frame-ancestors 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]
    assert "microphone=(self)" in headers["permissions-policy"]


def test_not_found_responses_also_carry_headers(admin_port: int) -> None:
    with pytest.raises(urllib.error.HTTPError) as caught:
        _headers(admin_port, "/assets/missing.js")
    assert caught.value.headers["x-content-type-options"] == "nosniff"


def test_model_download_range_and_missing_file(tmp_path: Path) -> None:
    model_root = tmp_path / "models"
    model_file = model_root / "v1" / "example" / "model.onnx"
    model_file.parent.mkdir(parents=True)
    model_file.write_bytes(b"0123456789")
    server = _start(tmp_path, "client", JALASE_NEGAR_MODELS_ROOT=str(model_root))
    port = next(server)
    try:
        url = f"http://127.0.0.1:{port}/jalase-negar-models/v1/example/model.onnx"
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310
            assert response.read() == b"0123456789"
            assert response.headers["Accept-Ranges"] == "bytes"
        request = urllib.request.Request(url, headers={"Range": "bytes=4-"})  # noqa: S310
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            assert response.status == 206
            assert response.headers["Content-Range"] == "bytes 4-9/10"
            assert response.read() == b"456789"
        for suffix, status in [("missing.onnx", 404), ("model.onnx", 416)]:
            request = urllib.request.Request(  # noqa: S310
                url.rsplit("/", 1)[0] + "/" + suffix, headers={"Range": "bytes=99-"}
            )
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=5)  # noqa: S310
            assert caught.value.code == status
    finally:
        server.close()
