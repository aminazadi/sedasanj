"""SMTP must verify certificates and never send credentials in clear text (WSTG-CRYP-03)."""

from __future__ import annotations

import smtplib
import ssl
from types import SimpleNamespace
from typing import Any

import pytest

from worker_notify import mailer


class _FakeSmtp:
    instances: list[_FakeSmtp] = []

    def __init__(self, *_args: Any, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.starttls_context: ssl.SSLContext | None = None
        self.logged_in = False
        self.sent = False
        self.supports_tls = True
        _FakeSmtp.instances.append(self)

    def __enter__(self) -> _FakeSmtp:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def starttls(self, context: ssl.SSLContext | None = None) -> None:
        if not self.supports_tls:
            raise smtplib.SMTPNotSupportedError("no starttls")
        self.starttls_context = context

    def login(self, *_args: Any) -> None:
        self.logged_in = True

    def send_message(self, *_args: Any) -> None:
        self.sent = True


def _settings(url: str) -> Any:
    return SimpleNamespace(smtp_url=url, notify_from_email="no-reply@example.com")


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSmtp.instances.clear()
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSmtp)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", _FakeSmtp)


def test_starttls_uses_a_verifying_context() -> None:
    mailer._send_sync(_settings("smtp://user:pw@mail.example.com:587"), "a@b.c", "s", "b")
    client = _FakeSmtp.instances[0]
    assert client.starttls_context is not None
    assert client.starttls_context.verify_mode == ssl.CERT_REQUIRED
    assert client.starttls_context.check_hostname is True
    assert client.logged_in and client.sent


def test_smtps_passes_a_verifying_context() -> None:
    mailer._send_sync(_settings("smtps://user:pw@mail.example.com:465"), "a@b.c", "s", "b")
    context = _FakeSmtp.instances[0].kwargs["context"]
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_credentials_are_never_sent_without_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NoTls(_FakeSmtp):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.supports_tls = False

    monkeypatch.setattr(mailer.smtplib, "SMTP", _NoTls)
    with pytest.raises(RuntimeError, match="TLS"):
        mailer._send_sync(_settings("smtp://user:pw@mail.example.com:587"), "a@b.c", "s", "b")
    assert not _FakeSmtp.instances[0].logged_in
    assert not _FakeSmtp.instances[0].sent
