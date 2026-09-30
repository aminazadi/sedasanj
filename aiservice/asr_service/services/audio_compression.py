"""Bounded gzip handling for ASR audio inputs."""

import gzip
import hashlib


class GzipAudioError(ValueError):
    """Raised when a declared gzip audio payload cannot be decoded safely."""


class BoundedReader:
    def __init__(self, source, maximum):
        self.source = source
        self.maximum = maximum
        self.size = 0
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        chunk = self.source.read(size)
        if chunk:
            self.size += len(chunk)
            if self.size > self.maximum:
                raise GzipAudioError("Compressed audio file is too large")
            self.digest.update(chunk)
        return chunk

    def readable(self):
        return True


def decompress_gzip(source, destination, *, maximum_bytes, expected_bytes=None, on_progress=None, maximum_encoded_bytes=None):
    """Decode gzip incrementally and return encoded/decoded sizes and digest."""
    reader = BoundedReader(source, maximum_encoded_bytes or maximum_bytes)
    decoded = 0
    try:
        with gzip.GzipFile(fileobj=reader, mode="rb") as archive:
            while chunk := archive.read(1024 * 1024):
                decoded += len(chunk)
                if decoded > maximum_bytes:
                    raise GzipAudioError("Uncompressed audio file is too large")
                if on_progress:
                    on_progress(decoded)
                if destination is not None:
                    destination.write(chunk)
    except (EOFError, gzip.BadGzipFile, OSError) as exc:
        raise GzipAudioError("Invalid gzip audio file") from exc
    if expected_bytes is not None and decoded != expected_bytes:
        raise GzipAudioError("Uncompressed audio size does not match declaration")
    return {"compressed_bytes": reader.size, "audio_bytes": decoded, "sha256": reader.digest.hexdigest()}
