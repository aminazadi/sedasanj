"""arq jobs must be JSON, never pickle (unpickling queue data is remote code execution)."""

from __future__ import annotations

import ast
import pickle
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.queue_serialization import job_deserializer, job_serializer

APPS = Path(__file__).resolve().parents[1] / "apps"


def test_round_trip_keeps_plain_values() -> None:
    call_id = str(uuid4())
    job = {"t": 1, "f": "transcribe_call", "a": [{"call_id": call_id}], "k": {}, "et": 7}
    assert job_deserializer(job_serializer(job)) == job


def test_non_json_values_are_stringified_instead_of_failing() -> None:
    value = uuid4()
    decoded = job_deserializer(job_serializer({"id": value}))
    assert decoded == {"id": str(value)}


def test_pickled_payload_is_rejected_not_executed() -> None:
    class Boom:
        def __reduce__(self) -> tuple[object, tuple[str]]:
            return (print, ("must never run",))

    with pytest.raises(ValueError):
        job_deserializer(pickle.dumps(Boom()))


def test_non_object_json_is_rejected() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        job_deserializer(b"[1, 2, 3]")


def test_every_worker_declares_the_json_serializer() -> None:
    mains = sorted(APPS.glob("worker_*/worker_*/main.py"))
    assert len(mains) >= 7
    for path in mains:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        settings = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "WorkerSettings"
        )
        assigned = {
            target.id
            for node in settings.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        assert {"job_serializer", "job_deserializer"} <= assigned, path.name
