from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class AmiClient:
    """Minimal AMI reader. The agent only listens; it never owns a channel (§4)."""

    def __init__(self, host: str, port: int, username: str, secret: str) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._secret = secret
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self._host, self._port)
        await self._reader.readline()  # AMI banner
        await self._send(
            {"Action": "Login", "Username": self._username, "Secret": self._secret, "Events": "on"}
        )

    async def _send(self, fields: dict[str, str]) -> None:
        if self._writer is None:
            raise RuntimeError("AMI not connected")
        payload = "".join(f"{key}: {value}\r\n" for key, value in fields.items()) + "\r\n"
        self._writer.write(payload.encode())
        await self._writer.drain()

    async def events(self) -> AsyncIterator[dict[str, str]]:
        if self._reader is None:
            raise RuntimeError("AMI not connected")
        block: dict[str, str] = {}
        while True:
            line = await self._reader.readline()
            if not line:
                raise ConnectionError("AMI connection closed")
            text = line.decode(errors="replace").strip()
            if not text:
                if block:
                    yield block
                    block = {}
                continue
            if ":" in text:
                key, _, value = text.partition(":")
                block[key.strip()] = value.strip()

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                logger.debug("AMI socket already closed")
        self._reader = None
        self._writer = None
