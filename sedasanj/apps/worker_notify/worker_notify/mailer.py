from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlparse

from app.config import Settings

logger = logging.getLogger(__name__)


def _send_sync(settings: Settings, to: str, subject: str, body: str) -> None:
    if not settings.smtp_url:
        logger.warning("SMTP_URL unset; skipping email", extra={"extra_fields": {"to": to}})
        return
    parsed = urlparse(settings.smtp_url)
    message = EmailMessage()
    message["From"] = settings.notify_from_email
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    host = parsed.hostname or "localhost"
    port = parsed.port or (465 if parsed.scheme == "smtps" else 587)
    # Always verify the server certificate and hostname; never send credentials in clear text.
    context = ssl.create_default_context()
    client: smtplib.SMTP | smtplib.SMTP_SSL
    if parsed.scheme == "smtps":
        client = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    else:
        client = smtplib.SMTP(host, port, timeout=30)
    with client:
        encrypted = parsed.scheme == "smtps"
        if parsed.scheme == "smtp":
            try:
                client.starttls(context=context)
                encrypted = True
            except smtplib.SMTPNotSupportedError:
                logger.warning("smtp server does not offer starttls; mail is sent unencrypted")
        if parsed.username and parsed.password:
            if not encrypted:
                raise RuntimeError(
                    "refusing to send SMTP credentials without TLS; use smtps:// or a server "
                    "that supports STARTTLS"
                )
            client.login(parsed.username, parsed.password)
        client.send_message(message)


async def send_email(settings: Settings, to: str, subject: str, body: str) -> None:
    await asyncio.to_thread(_send_sync, settings, to, subject, body)
