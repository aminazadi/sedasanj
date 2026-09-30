"""Private S3-compatible object storage for direct, resumable audio uploads."""

import hashlib
import os
import re
from pathlib import Path

PART_SIZE = max(5 * 1024 * 1024, int(os.getenv("ASR_UPLOAD_PART_SIZE_MB", "16")) * 1024 * 1024)
URL_TTL_SECONDS = max(60, int(os.getenv("ASR_UPLOAD_URL_TTL_SECONDS", "900")))


def enabled():
    # Refuse to issue unusable URLs that point to Docker's private network.
    return all(os.getenv(name, "").strip() for name in ("ASR_S3_BUCKET", "ASR_S3_ENDPOINT", "ASR_S3_PUBLIC_ENDPOINT"))


def _client(public=False):
    # Keep legacy/local test environments usable when direct uploads are not
    # configured. The runtime image always installs boto3.
    import boto3
    from botocore.config import Config

    if not enabled():
        raise RuntimeError("Direct object uploads are not configured")
    kwargs = {
        "service_name": "s3",
        "region_name": os.getenv("ASR_S3_REGION", "us-east-1"),
        "aws_access_key_id": os.getenv("ASR_S3_ACCESS_KEY", ""),
        "aws_secret_access_key": os.getenv("ASR_S3_SECRET_KEY", ""),
        "config": Config(signature_version="s3v4", s3={"addressing_style": os.getenv("ASR_S3_ADDRESSING_STYLE", "path")}),
    }
    endpoint = os.getenv("ASR_S3_PUBLIC_ENDPOINT" if public else "ASR_S3_ENDPOINT", "").strip()
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client(**kwargs)


def bucket():
    return os.getenv("ASR_S3_BUCKET", "").strip()


def safe_filename(name):
    value = Path(name or "audio").name
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)[:180] or "audio"


def create_multipart(key, content_type=None, metadata=None):
    args = {"Bucket": bucket(), "Key": key, "Metadata": metadata or {}}
    if content_type:
        args["ContentType"] = content_type
    return _client().create_multipart_upload(**args)["UploadId"]


def part_url(key, backend_upload_id, part_number):
    # The signature must contain the browser-reachable hostname, not Docker's
    # internal ``minio`` hostname. Server-side operations keep using the
    # private endpoint from ASR_S3_ENDPOINT.
    return _client(public=True).generate_presigned_url(
        "upload_part",
        Params={"Bucket": bucket(), "Key": key, "UploadId": backend_upload_id, "PartNumber": part_number},
        ExpiresIn=URL_TTL_SECONDS,
        HttpMethod="PUT",
    )


def complete_multipart(key, backend_upload_id, parts):
    return _client().complete_multipart_upload(
        Bucket=bucket(), Key=key, UploadId=backend_upload_id,
        MultipartUpload={"Parts": [{"ETag": item["etag"], "PartNumber": item["part_number"]} for item in parts]},
    )


def abort_multipart(key, backend_upload_id):
    return _client().abort_multipart_upload(Bucket=bucket(), Key=key, UploadId=backend_upload_id)


def head(key):
    return _client().head_object(Bucket=bucket(), Key=key)


def open_object(key):
    return _client().get_object(Bucket=bucket(), Key=key)["Body"]


def download(key, destination):
    digest = hashlib.sha256()
    size = 0
    with _client().get_object(Bucket=bucket(), Key=key)["Body"] as source, open(destination, "wb") as output:
        while chunk := source.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def delete(key):
    _client().delete_object(Bucket=bucket(), Key=key)
