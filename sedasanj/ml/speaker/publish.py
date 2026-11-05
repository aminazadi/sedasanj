"""Publish a trained speaker model (an ONNX file plus metadata) to the SedaSanj model registry.

This script converts nothing: export the model to ONNX first. It sends the file and its metadata
to ``POST /v1/ml/models`` with the publisher API key, which is read from the environment and is
never printed or logged.

Environment (names only; set the values on the GPU server, never in the repository):
    ML_PUBLISH_URL      base URL of the API, for example https://panel.example.com
    ML_PUBLISH_API_KEY  the publisher key created by scripts/create_ml_publisher_key.py

Example:
    python publish.py model.onnx --kind speaker_embedding --version 2026.11.05-1 \
        --dim 192 --sample-rate 16000 --metrics metrics.json --training-run-id run-42
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

CHANNELS = ("latest", "champion")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_metadata(args: argparse.Namespace, digest: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if args.metrics:
        metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
    metadata: dict[str, Any] = {
        "kind": args.kind,
        "version": args.version,
        "sha256": digest,
        "metrics": metrics,
    }
    for field, value in (
        ("dim", args.dim),
        ("sample_rate", args.sample_rate),
        ("dataset_manifest_hash", args.dataset_manifest_hash),
        ("training_run_id", args.training_run_id),
        ("signature", args.signature),
    ):
        if value is not None:
            metadata[field] = value
    return metadata


def encode_multipart(metadata: dict[str, Any], model: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="metadata"\r\n\r\n'
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{model.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head + model.read_bytes() + tail, f"multipart/form-data; boundary={boundary}"


def publish(model: Path, args: argparse.Namespace) -> dict[str, Any]:
    base = os.environ.get("ML_PUBLISH_URL", "").rstrip("/")
    key = os.environ.get("ML_PUBLISH_API_KEY", "")
    if not base or not key:
        raise SystemExit("set ML_PUBLISH_URL and ML_PUBLISH_API_KEY in the environment")
    body, content_type = encode_multipart(build_metadata(args, sha256_file(model)), model)
    request = urllib.request.Request(  # noqa: S310 - the URL comes from the operator's environment
        f"{base}/v1/ml/models?channel={args.channel}",
        data=body,
        method="POST",
        headers={"X-API-Key": key, "Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:  # noqa: S310
            result: dict[str, Any] = json.loads(response.read())
            return result
    except urllib.error.HTTPError as error:
        # The body carries only the error code and message, never the key.
        raise SystemExit(
            f"publish failed: HTTP {error.code} {error.read().decode()[:500]}"
        ) from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("model", type=Path, help="the ONNX file")
    parser.add_argument("--kind", required=True, help="for example speaker_embedding")
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=CHANNELS, default="latest")
    parser.add_argument("--dim", type=int)
    parser.add_argument("--sample-rate", type=int)
    parser.add_argument("--metrics", help="path to a JSON file with evaluation metrics")
    parser.add_argument("--dataset-manifest-hash")
    parser.add_argument("--training-run-id")
    parser.add_argument("--signature")
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()
    if not args.model.is_file():
        raise SystemExit(f"{args.model} is not a file")
    result = publish(args.model, args)
    state = "already published" if result.get("already_published") else "published"
    print(f"{state}: {result['kind']} {result['version']} sha256={result['sha256']}")


if __name__ == "__main__":
    sys.exit(main())
