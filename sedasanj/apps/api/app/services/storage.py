from __future__ import annotations

import abc
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
    async def delete(self, key: str) -> None: ...

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

    async def delete(self, key: str) -> None:
        async with self._client() as client:
            await client.delete_object(Bucket=self.bucket, Key=key)

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

    async def ensure_bucket(self) -> None:
        return None

    async def put(self, key: str, body: bytes, content_type: str = "audio/wav") -> None:
        self.objects[key] = body

    async def put_path(self, key: str, path: Path, content_type: str = "audio/wav") -> None:
        self.objects[key] = path.read_bytes()

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

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
