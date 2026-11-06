from __future__ import annotations

import abc
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aioboto3

from app.config import Settings, get_settings


class Storage(abc.ABC):
    """Object store used for the original upload (§2)."""

    bucket: str

    @abc.abstractmethod
    async def put(self, key: str, body: bytes, content_type: str = "audio/wav") -> None: ...

    @abc.abstractmethod
    async def put_path(self, key: str, path: Path, content_type: str = "audio/wav") -> None: ...

    @abc.abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abc.abstractmethod
    def iter_chunks(
        self, key: str, chunk_size: int = 1024 * 1024, byte_range: tuple[int, int] | None = None
    ) -> AsyncIterator[bytes]:
        """Stream the object; ``byte_range`` is an inclusive ``(first, last)`` byte window."""
        ...

    @abc.abstractmethod
    async def delete(self, key: str) -> None: ...

    @abc.abstractmethod
    async def list_keys(self, prefix: str) -> list[tuple[str, datetime]]:
        """Every object under ``prefix`` with its last-modified time (UTC)."""
        ...

    @abc.abstractmethod
    def iter_sizes(self, prefix: str) -> AsyncGenerator[int, None]:
        """Object sizes under the prefix, fetched incrementally."""
        ...

    @abc.abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abc.abstractmethod
    async def presigned_url(self, key: str, expires_in: int) -> str: ...

    @abc.abstractmethod
    async def ensure_bucket(self) -> None: ...

    @abc.abstractmethod
    async def ping(self) -> bool: ...


class S3Storage(Storage):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = aioboto3.Session()
        self.bucket = settings.minio_bucket_audio

    def _client(self, *, public: bool = False) -> Any:
        return self._session.client(
            "s3",
            endpoint_url=(
                self._settings.presign_endpoint if public else self._settings.minio_endpoint
            ),
            aws_access_key_id=self._settings.minio_access_key,
            aws_secret_access_key=self._settings.minio_secret_key,
            region_name=self._settings.minio_region,
        )

    async def ensure_bucket(self) -> None:
        async with self._client() as client:
            try:
                await client.head_bucket(Bucket=self.bucket)
            except Exception:
                await client.create_bucket(Bucket=self.bucket)

    async def put(self, key: str, body: bytes, content_type: str = "audio/wav") -> None:
        async with self._client() as client:
            await client.put_object(
                Bucket=self.bucket, Key=key, Body=body, ContentType=content_type
            )

    async def put_path(self, key: str, path: Path, content_type: str = "audio/wav") -> None:
        async with self._client() as client:
            with path.open("rb") as handle:
                await client.upload_fileobj(
                    handle,
                    self.bucket,
                    key,
                    ExtraArgs={"ContentType": content_type},
                )

    async def get(self, key: str) -> bytes:
        async with self._client() as client:
            response = await client.get_object(Bucket=self.bucket, Key=key)
            data: bytes = await response["Body"].read()
            return data

    async def iter_chunks(
        self, key: str, chunk_size: int = 1024 * 1024, byte_range: tuple[int, int] | None = None
    ) -> AsyncIterator[bytes]:
        async with self._client() as client:
            options = {"Range": f"bytes={byte_range[0]}-{byte_range[1]}"} if byte_range else {}
            response = await client.get_object(Bucket=self.bucket, Key=key, **options)
            body = response["Body"]
            try:
                # iter_chunks works across aiobotocore versions; `async with` yields a raw
                # aiohttp response whose read() takes no size and broke the download mid-stream.
                async for chunk in body.iter_chunks(chunk_size):
                    yield chunk
            finally:
                body.close()

    async def delete(self, key: str) -> None:
        async with self._client() as client:
            await client.delete_object(Bucket=self.bucket, Key=key)

    async def list_keys(self, prefix: str) -> list[tuple[str, datetime]]:
        found: list[tuple[str, datetime]] = []
        async with self._client() as client:
            token: str | None = None
            while True:
                options: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix}
                if token:
                    options["ContinuationToken"] = token
                page = await client.list_objects_v2(**options)
                for item in page.get("Contents", []):
                    modified = item["LastModified"]
                    if modified.tzinfo is None:
                        modified = modified.replace(tzinfo=UTC)
                    found.append((item["Key"], modified))
                if not page.get("IsTruncated"):
                    return found
                token = page.get("NextContinuationToken")

    async def exists(self, key: str) -> bool:
        async with self._client() as client:
            try:
                await client.head_object(Bucket=self.bucket, Key=key)
            except client.exceptions.ClientError as error:
                code = str(error.response.get("Error", {}).get("Code", ""))
                if code in {"404", "NoSuchKey", "NotFound"}:
                    return False
                raise
            return True

    async def iter_sizes(self, prefix: str) -> AsyncGenerator[int, None]:
        async with self._client() as client:
            pages = client.get_paginator("list_objects_v2")
            async for page in pages.paginate(Bucket=self.bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    yield int(item["Size"])

    async def presigned_url(self, key: str, expires_in: int) -> str:
        async with self._client(public=True) as client:
            url: str = await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
            return url

    async def ping(self) -> bool:
        async with self._client() as client:
            await client.head_bucket(Bucket=self.bucket)
            return True


class MemoryStorage(Storage):
    """In-process store for tests and local runs without MinIO."""

    def __init__(self, bucket: str = "audio") -> None:
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}
        self.modified: dict[str, datetime] = {}

    async def ensure_bucket(self) -> None:
        return None

    async def put(self, key: str, body: bytes, content_type: str = "audio/wav") -> None:
        self.objects[key] = body
        self.modified[key] = datetime.now(UTC)

    async def put_path(self, key: str, path: Path, content_type: str = "audio/wav") -> None:
        self.objects[key] = path.read_bytes()
        self.modified[key] = datetime.now(UTC)

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def iter_chunks(
        self, key: str, chunk_size: int = 1024 * 1024, byte_range: tuple[int, int] | None = None
    ) -> AsyncIterator[bytes]:
        data = self.objects[key]
        if byte_range:
            data = data[byte_range[0] : byte_range[1] + 1]
        for offset in range(0, len(data), chunk_size):
            yield data[offset : offset + chunk_size]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)
        self.modified.pop(key, None)

    async def list_keys(self, prefix: str) -> list[tuple[str, datetime]]:
        return [
            (key, self.modified.get(key, datetime.now(UTC)))
            for key in sorted(self.objects)
            if key.startswith(prefix)
        ]

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def iter_sizes(self, prefix: str) -> AsyncGenerator[int, None]:
        for key, data in self.objects.items():
            if key.startswith(prefix):
                yield len(data)

    async def presigned_url(self, key: str, expires_in: int) -> str:
        return f"memory://{self.bucket}/{key}?expires_in={expires_in}"

    async def ping(self) -> bool:
        return True


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        settings = get_settings()
        _storage = (
            MemoryStorage(settings.minio_bucket_audio)
            if settings.storage_backend == "memory"
            else S3Storage(settings)
        )
    return _storage


def set_storage(storage: Storage | None) -> None:
    global _storage
    _storage = storage
