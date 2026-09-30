import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from asr_service.api.schemas.requests import CustomTextModelRequest, DecisionRequest
from asr_service.api.routers import models
from asr_service.api.schemas.responses import TaskResponse
from asr_service.domain.catalog import CATALOG, ModelSpec
from asr_service.infrastructure import storage
from asr_service.services import decision_processing


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        storage.DATA_DIR = root
        storage.MODEL_DIR = root / "models"
        storage.DB_PATH = root / "asr.sqlite3"
        storage.init_db()
        self.spec = ModelSpec("decision-test", "decision", "Decision", "", "", engine="laya", task="decision")
        CATALOG[self.spec.id] = self.spec
        model_dir = storage.MODEL_DIR / self.spec.id
        model_dir.mkdir(parents=True)
        (model_dir / ".complete").write_text("ok")

    def tearDown(self):
        CATALOG.pop(self.spec.id, None)
        self.temp.cleanup()

    def test_direct_decision_models_require_checksums(self):
        with self.assertRaises(ValueError):
            CustomTextModelRequest(
                id="unsafe", display_name="unsafe", kind="decision", engine="laya",
                files=[{"filename": "config.json", "download_url": "https://example.com/config.json"}],
            )

    def test_direct_decision_url_rejects_private_or_credentialed_hosts(self):
        for url in ("https://127.0.0.1/model.safetensors", "https://user:pass@example.com/model.safetensors"):
            with self.assertRaises(ValueError):
                CustomTextModelRequest(
                    id="secure-direct", display_name="Secure direct", kind="decision", engine="laya",
                    files=[{"filename": "model.safetensors", "download_url": url, "sha256": "a" * 64}],
                )

    def test_hugging_face_decision_requires_immutable_revision(self):
        with self.assertRaises(ValueError):
            CustomTextModelRequest(
                id="mutable", display_name="mutable", kind="decision", engine="laya",
                source_type="huggingface", hf_repository="org/model", revision="main",
            )

    def test_hugging_face_tree_resolves_lfs_and_small_file_checksums(self):
        body = CustomTextModelRequest(
            id="pinned", display_name="Pinned", kind="decision", engine="gliner2_decide",
            source_type="huggingface", hf_repository="owner/model", revision="a" * 40,
        )

        class Response:
            def __init__(self, payload=None, chunks=()):
                self.payload = payload
                self.chunks = chunks

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

            def iter_content(self, _):
                return iter(self.chunks)

        def get(url, **_):
            if "/revision/" in url:
                return Response({"sha": "a" * 40, "private": False, "gated": False})
            if "/tree/" in url:
                return Response([
                    {"type": "file", "path": "config.json"},
                    {"type": "file", "path": "model.safetensors", "lfs": {"oid": "b" * 64, "size": 42}},
                ])
            return Response(chunks=(b"{}",))

        with patch.object(models, "requests", SimpleNamespace(get=get)):
            files = models._resolve_hugging_face_artifacts(body)
        self.assertEqual({item["filename"] for item in files}, {"config.json", "model.safetensors"})
        self.assertEqual(next(item for item in files if item["filename"] == "model.safetensors")["sha256"], "b" * 64)
        self.assertEqual(len(next(item for item in files if item["filename"] == "config.json")["sha256"]), 64)

    def test_normalized_low_confidence_answer_abstains(self):
        class Model:
            def predict(self, state, questions):
                return {"route": {"confidence": .4, "probabilities": {"a": .4, "b": .3}}}

        @contextmanager
        def lease(model_id):
            yield Model()

        with patch.object(decision_processing.registry, "lease", lease):
            result = decision_processing.decide(self.spec.id, "hello", {
                "route": {"type": "choice", "instructions": "route", "criteria": {"a": "A", "b": "B"}}
            }, .72)
        self.assertTrue(result["answers"]["route"]["abstained"])
        self.assertIsNone(result["answers"]["route"]["answer"])

    def test_gliner_and_laya_native_answers_are_normalized(self):
        class GLiNER:
            def classify_text(self, state, schema, include_confidence):
                if not include_confidence:
                    raise AssertionError("GLiNER confidence metadata was not requested")
                return {"route": {"label": "refund", "confidence": .91}}

        class Laya:
            def predict(self, state, questions):
                return {"answers": {"route": {"choice": "refund", "confidence": .93, "probabilities": {"refund": .93, "other": .07}}}}

        @contextmanager
        def gliner_lease(model_id):
            yield GLiNER()

        gliner_spec = ModelSpec("gliner-test", "decision", "GLiNER", "", "", engine="gliner2_decide", task="decision")
        CATALOG[gliner_spec.id] = gliner_spec
        try:
            with patch.object(decision_processing.registry, "lease", gliner_lease):
                gliner = decision_processing.decide(gliner_spec.id, "hello", {"route": {"type": "choice", "instructions": "route", "criteria": ["refund", "other"]}})
            self.assertEqual(gliner["answers"]["route"]["answer"], "refund")
        finally:
            CATALOG.pop(gliner_spec.id, None)

        @contextmanager
        def laya_lease(model_id):
            yield Laya()

        with patch.object(decision_processing.registry, "lease", laya_lease):
            laya = decision_processing.decide(self.spec.id, "hello", {"route": {"type": "choice", "instructions": "route", "criteria": ["refund", "other"]}})
        self.assertEqual(laya["answers"]["route"]["answer"], "refund")

    def test_decision_task_runs_in_durable_queue(self):
        from asr_service.services import task_queue
        task_queue.TASK_DIR = storage.DATA_DIR / "tasks"
        task_queue.POLL_SECONDS = .01
        manager = task_queue.TaskManager()
        manager.start()
        try:
            with patch("asr_service.services.decision_processing.decide", return_value={"model": self.spec.id, "answers": {}}):
                task, _ = task_queue.enqueue("decision", self.spec.id, input_data={"state": "سلام", "questions": {}, "confidence_threshold": .72})
                for _ in range(100):
                    current = task_queue.get_task(task["task_id"])
                    if current["status"] == "succeeded":
                        break
                    time.sleep(.02)
            self.assertEqual("succeeded", current["status"])
        finally:
            manager.stop()

    def test_decision_task_uses_default_threshold_when_request_omits_it(self):
        from asr_service.services import task_queue
        task_queue.TASK_DIR = storage.DATA_DIR / "tasks"
        task_queue.POLL_SECONDS = .01
        manager = task_queue.TaskManager()
        manager.start()
        try:
            with patch("asr_service.services.decision_processing.decide", return_value={"model": self.spec.id, "answers": {}}) as decide:
                task, _ = task_queue.enqueue("decision", self.spec.id, input_data={"state": "سلام", "questions": {}, "confidence_threshold": None})
                for _ in range(100):
                    current = task_queue.get_task(task["task_id"])
                    if current["status"] == "succeeded":
                        break
                    time.sleep(.02)
            self.assertEqual("succeeded", current["status"])
            self.assertEqual(decide.call_args.args[3], .72)
        finally:
            manager.stop()

    def test_decision_request_accepts_typed_questions(self):
        request = DecisionRequest(model=self.spec.id, state={"text": "سلام"}, questions={"route": {"type": "choice", "instructions": "route", "criteria": {"a": "A"}}})
        self.assertEqual(self.spec.id, request.model)

    def test_decision_task_response_is_schema_valid(self):
        response = TaskResponse.model_validate({
            "task_id": "task", "kind": "decision", "status": "queued",
            "created_at": "2026-09-29T00:00:00+00:00", "updated_at": "2026-09-29T00:00:00+00:00",
            "model_id": self.spec.id, "response_format": "json", "attempts": 0,
            "max_attempts": 2, "status_url": "/v1/tasks/task",
        })
        self.assertEqual(response.kind, "decision")
