"""JSON job serialization for arq.

arq pickles jobs by default, and unpickling attacker-controlled bytes executes code. Redis
is an internal service, but it must not become a code-execution primitive for any process that
can reach it, so every producer and worker uses JSON instead (WSTG-CONF / CWE-502).
"""

from __future__ import annotations

import json
from typing import Any


def job_serializer(value: dict[str, Any]) -> bytes:
    # `default=str` keeps UUID/datetime values that a caller forgot to stringify from
    # failing the whole enqueue; the worker receives their string form.
    return json.dumps(value, separators=(",", ":"), default=str).encode("utf-8")


def job_deserializer(payload: bytes) -> dict[str, Any]:
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("job payload must be a JSON object")
    return decoded
