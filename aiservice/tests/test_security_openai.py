import asyncio
import json
import importlib.util
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

if importlib.util.find_spec("requests") is None:
    requests = types.ModuleType("requests")
    requests.Session = object
    requests.HTTPError = type("HTTPError", (Exception,), {})
    requests.RequestException = type("RequestException", (Exception,), {})
    sys.modules["requests"] = requests

from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from asr_service.api import dependencies
from asr_service.api.routers import analytics, models, openai_compat, security
from asr_service.api.cors import DynamicCORSMiddleware
from asr_service.api.failure_audit import RequestFailureAuditMiddleware
from asr_service.api.routers.openai_compat import ChatCompletionRequest, EmbeddingRequest
from asr_service.api.schemas.requests import CustomModelFileRequest, CustomTextModelRequest
from asr_service.domain.catalog import CATALOG, ModelSpec, load_custom_models
from asr_service.infrastructure import storage
from asr_service.services import downloader


class SecurityAndCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [
            patch.object(storage, "DATA_DIR", root),
            patch.object(storage, "DB_PATH", root / "test.sqlite3"),
            patch.object(storage, "MODEL_DIR", root / "models"),
            patch.object(models, "MODEL_DIR", root / "models"),
            patch.object(downloader, "MODEL_DIR", root / "models"),
            patch.object(openai_compat, "MODEL_DIR", root / "models"),
        ]
        for item in self.patches:
            item.start()
        storage.init_db()

    def tearDown(self):
        for model_id in list(CATALOG):
            if model_id.startswith("test-"):
                CATALOG.pop(model_id)
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_issued_key_is_non_admin_and_can_be_blocked(self):
        created = security.create_key(security.ApiKeyCreate(name="client"))
        principal = dependencies.authorize(f"Bearer {created['api_key']}")
        self.assertFalse(principal.is_admin)
        with self.assertRaises(HTTPException) as denied:
            dependencies.authorize_admin(principal)
        self.assertEqual(denied.exception.status_code, 403)
        security.update_key(created["id"], security.ApiKeyUpdate(enabled=False))
        with self.assertRaises(HTTPException) as blocked:
            dependencies.authorize(f"Bearer {created['api_key']}")
        self.assertEqual(blocked.exception.status_code, 401)

    def test_issued_key_can_be_deleted(self):
        created = security.create_key(security.ApiKeyCreate(name="temporary"))
        response = security.delete_key(created["id"])
        self.assertEqual(response.status_code, 204)
        self.assertIsNone(storage.row("SELECT id FROM api_keys WHERE id=?", (created["id"],)))
        with self.assertRaises(HTTPException) as deleted:
            dependencies.authorize(f"Bearer {created['api_key']}")
        self.assertEqual(deleted.exception.status_code, 401)
        with self.assertRaises(HTTPException) as missing:
            security.delete_key(created["id"])
        self.assertEqual(missing.exception.status_code, 404)

    def test_naive_expiration_is_normalized_and_narrow_scope_can_poll(self):
        created = security.create_key(
            security.ApiKeyCreate(
                name="transcriber",
                scopes=["transcription"],
                expires_at=datetime(2099, 1, 1),
            )
        )
        principal = dependencies.authorize(f"bearer {created['api_key']}")
        dependencies.require_access(principal, "inference")
        self.assertTrue(created["expires_at"].endswith("+00:00"))

    def test_model_listing_respects_installation_scope_and_model_allowlist(self):
        for model_id, kind in (("test-speech", "asr"), ("test-text", "llm"), ("test-pending", "asr")):
            CATALOG[model_id] = next(spec for spec in CATALOG.values() if spec.kind == kind)
            if model_id != "test-pending":
                folder = storage.MODEL_DIR / model_id
                folder.mkdir(parents=True)
                (folder / ".complete").touch()
        speech = dependencies.Principal(False, scopes=("transcription",))
        text = dependencies.Principal(False, scopes=("chat",))
        limited = dependencies.Principal(False, scopes=("inference",), models=("test-speech",))
        self.assertEqual([item["id"] for item in openai_compat.list_models("asr", speech)["data"]], ["test-speech"])
        self.assertEqual([item["id"] for item in openai_compat.list_models("llm", text)["data"]], ["test-text"])
        self.assertEqual([item["id"] for item in openai_compat.list_models("asr", limited)["data"]], ["test-speech"])
        self.assertEqual([item["id"] for item in openai_compat.list_models("llm", dependencies.Principal(True))["data"]], ["test-text"])
        self.assertEqual({item["kind"] for item in openai_compat.list_models("all", dependencies.Principal(True))["data"]}, {"asr", "llm"})
        with self.assertRaises(HTTPException) as denied:
            openai_compat.list_models("llm", dependencies.Principal(False))
        self.assertEqual(denied.exception.status_code, 403)

    def test_local_embedding_endpoint_returns_openai_shape(self):
        body = EmbeddingRequest(model="test-embedding", input=["first", "second"])
        with patch(
            "asr_service.services.embedding_processing.embed",
            return_value=([[0.1, 0.2], [0.3, 0.4]], 4),
        ):
            result = asyncio.run(
                openai_compat.create_embeddings(body, dependencies.Principal(True))
            )
        self.assertEqual(result["model"], "test-embedding")
        self.assertEqual(result["data"][1]["index"], 1)
        self.assertEqual(result["usage"]["total_tokens"], 4)

    def test_embedding_model_appears_in_user_catalog(self):
        CATALOG["test-embedding"] = ModelSpec(
            "test-embedding",
            "embedding",
            "Test Embedding",
            "",
            "",
        )
        folder = storage.MODEL_DIR / "test-embedding"
        folder.mkdir(parents=True)
        (folder / ".complete").touch()
        result = openai_compat.list_models("embedding", dependencies.Principal(True))
        self.assertEqual(result["data"][0]["id"], "test-embedding")
        self.assertEqual(result["data"][0]["kind"], "embedding")

    def test_executable_remote_model_is_reported_as_ready_independent_of_owner(self):
        with (
            patch(
                "asr_service.api.routers.openai_compat.cached_models",
                return_value=[{"id": "openai/gpt-test", "kind": "llm", "owned_by": "openai"}],
            ),
            patch(
                "asr_service.api.routers.openai_compat.configured_models",
                return_value={"openai/gpt-test"},
            ),
        ):
            result = openai_compat.list_models("llm", dependencies.Principal(True))
        remote = next(item for item in result["data"] if item["id"] == "openai/gpt-test")
        self.assertEqual(remote["owned_by"], "openai")
        self.assertEqual(remote["source"], "9router")
        self.assertTrue(remote["available"])
        self.assertEqual(remote["status"], "ready")

    def test_embedding_model_requires_pinned_safe_bundle(self):
        with self.assertRaises(ValueError):
            CustomTextModelRequest(
                id="test-embedding",
                display_name="Test Embedding",
                kind="embedding",
                source_type="huggingface",
                hf_repository="org/model",
                revision="main",
            )

    def test_custom_gguf_model_persists_and_enters_catalog(self):
        result = models.add_model(
            CustomTextModelRequest(
                id="test-custom",
                display_name="Test Custom",
                download_url="https://example.com/model.gguf",
                filename="model.gguf",
                sha256="a" * 64,
            )
        )
        self.assertEqual(result["kind"], "llm")
        CATALOG.pop("test-custom")
        load_custom_models()
        self.assertEqual(CATALOG["test-custom"].files[0].sha256, "a" * 64)

    def test_custom_faster_whisper_model_is_an_asr_model(self):
        names = [
            "model.bin", "config.json", "tokenizer.json", "vocabulary.json",
            "preprocessor_config.json",
        ]
        result = models.add_model(CustomTextModelRequest(
            id="test-turbo", kind="asr", display_name="Whisper Turbo",
            description="CTranslate2 bundle",
            files=[CustomModelFileRequest(
                filename=name, download_url=f"https://example.com/turbo/{name}"
            ) for name in names],
        ))
        self.assertEqual(result["kind"], "asr")
        self.assertEqual(result["architecture"], "fasterWhisper")
        self.assertEqual([item["filename"] for item in result["files"]], names)
        CATALOG.pop("test-turbo")
        load_custom_models()
        self.assertEqual(CATALOG["test-turbo"].architecture, "fasterWhisper")
        self.assertEqual(len(CATALOG["test-turbo"].files), 5)

    def test_custom_model_can_be_edited_and_assigned_to_asr(self):
        models.add_model(CustomTextModelRequest(
            id="test-edit", display_name="Text Model",
            download_url="https://example.com/text.gguf", filename="text.gguf",
        ))
        names = ["model.bin", "config.json", "tokenizer.json", "vocabulary.json", "preprocessor_config.json"]
        result = models.update_model("test-edit", CustomTextModelRequest(
            id="test-edit", kind="asr", display_name="Speech Model",
            files=[CustomModelFileRequest(
                filename=name, download_url=f"https://example.com/speech/{name}"
            ) for name in names],
        ))
        self.assertEqual(result["kind"], "asr")
        self.assertTrue(result["custom"])
        self.assertEqual(CATALOG["test-edit"].architecture, "fasterWhisper")

    def test_delete_custom_model_removes_installed_and_partial_files_and_definition(self):
        models.add_model(CustomTextModelRequest(
            id="test-delete", display_name="Delete Me",
            download_url="https://example.com/model.gguf", filename="model.gguf",
        ))
        installed = storage.MODEL_DIR / "test-delete"
        staging = storage.MODEL_DIR / "test-delete.staging"
        installed.mkdir()
        staging.mkdir()
        (installed / "model.gguf").write_bytes(b"installed")
        (staging / "model.gguf.part").write_bytes(b"partial")
        storage.set_state("test-delete", status="installed", received_bytes=9)

        self.assertEqual(models.delete_model("test-delete").status_code, 204)
        self.assertFalse(installed.exists())
        self.assertFalse(staging.exists())
        self.assertNotIn("test-delete", CATALOG)
        self.assertIsNone(storage.row("SELECT model_id FROM custom_models WHERE model_id='test-delete'"))
        self.assertIsNone(storage.row("SELECT model_id FROM model_state WHERE model_id='test-delete'"))

    def test_delete_builtin_removes_files_and_keeps_reinstall_option(self):
        installed = storage.MODEL_DIR / "silero-vad"
        installed.mkdir()
        (installed / ".complete").touch()
        storage.set_state("silero-vad", status="installed", received_bytes=7)

        self.assertEqual(models.delete_model("silero-vad").status_code, 204)
        self.assertFalse(installed.exists())
        self.assertIn("silero-vad", CATALOG)
        self.assertEqual(storage.state("silero-vad")["status"], "not_installed")

    def test_delete_uninstalled_custom_model(self):
        models.add_model(CustomTextModelRequest(
            id="test-uninstalled", display_name="Never Installed",
            download_url="https://example.com/model.gguf", filename="model.gguf",
        ))
        self.assertEqual(models.delete_model("test-uninstalled").status_code, 204)
        self.assertNotIn("test-uninstalled", CATALOG)

    def test_delete_paused_model_clears_partial_download(self):
        staging = storage.MODEL_DIR / "silero-vad.staging"
        staging.mkdir()
        (staging / "silero_vad.onnx.part").write_bytes(b"partial")
        storage.set_state("silero-vad", status="paused", received_bytes=7)
        self.assertEqual(models.delete_model("silero-vad").status_code, 204)
        self.assertFalse(staging.exists())
        self.assertEqual(storage.state("silero-vad")["status"], "not_installed")

    def test_delete_rejects_active_task_without_losing_files(self):
        installed = storage.MODEL_DIR / "silero-vad"
        installed.mkdir()
        (installed / ".complete").touch()
        storage.execute(
            "INSERT INTO tasks(task_id,kind,status,created_at,available_at,updated_at,model_id) VALUES(?,?,?,?,?,?,?)",
            ("test-running", "asr", "running", storage.now(), storage.now(), storage.now(), "silero-vad"),
        )
        with self.assertRaises(HTTPException) as blocked:
            models.delete_model("silero-vad")
        self.assertEqual(blocked.exception.status_code, 409)
        self.assertTrue((installed / ".complete").exists())

    def test_chat_completion_has_openai_shape_and_model(self):
        models.add_model(
            CustomTextModelRequest(
                id="test-chat",
                display_name="Test Chat",
                download_url="https://example.com/chat.gguf",
                filename="chat.gguf",
            )
        )
        folder = storage.MODEL_DIR / "test-chat"
        folder.mkdir(parents=True)
        (folder / ".complete").touch()
        raw = {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "سلام"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }
        body = ChatCompletionRequest(
            model="test-chat", messages=[{"role": "user", "content": "سلام"}]
        )
        queued = {"task_id": "chat-test", "status": "succeeded", "result_json": json.dumps(raw)}
        with patch.object(openai_compat, "enqueue", return_value=(queued, True)):
            response = asyncio.run(
                openai_compat.create_completion(
                    body,
                    Request({"type": "http", "client": ("127.0.0.1", 1)}),
                    dependencies.Principal(True),
                )
            )
        self.assertEqual(response["object"], "chat.completion")
        self.assertEqual(response["model"], "test-chat")
        self.assertTrue(response["id"].startswith("chatcmpl-"))
        self.assertEqual(response["choices"][0]["message"]["content"], "سلام")

    def test_cors_policy_round_trips(self):
        value = security.CorsPolicy(
            allowed_origins=["https://app.example"], allowed_ips=["10.0.0.0/8"]
        )
        security.put_cors(value)
        loaded = security.get_cors_policy()
        self.assertEqual(loaded.allowed_origins, value.allowed_origins)
        self.assertEqual(loaded.allowed_ips, value.allowed_ips)

    def test_cors_rejects_unapproved_preflight_headers(self):
        security.put_cors(
            security.CorsPolicy(allowed_origins=["https://app.example"])
        )
        app = FastAPI()
        app.add_middleware(DynamicCORSMiddleware)

        @app.get("/v1/check")
        def check():
            return {"ok": True}

        response = TestClient(app).options(
            "/v1/check",
            headers={
                "Origin": "https://app.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Forbidden",
            },
        )
        self.assertEqual(response.status_code, 403)
        event = storage.row("SELECT * FROM security_rejections")
        self.assertEqual(event["reason"], "cors_policy_not_allowed")
        self.assertEqual(event["origin"], "https://app.example")
        self.assertEqual(event["requested_headers"], "X-Forbidden")
        self.assertIsNone(event.get("authorization"))

    def test_ip_and_origin_rejections_are_persisted_and_listed(self):
        security.put_cors(
            security.CorsPolicy(
                allowed_origins=["https://allowed.example"],
                allowed_ips=["10.0.0.0/8"],
            )
        )
        app = FastAPI()
        app.add_middleware(DynamicCORSMiddleware)

        @app.get("/v1/check")
        def check():
            return {"ok": True}

        response = TestClient(app).get(
            "/v1/check?probe=1",
            headers={"Origin": "https://blocked.example", "X-Forwarded-For": "203.0.113.9"},
        )
        self.assertEqual(response.status_code, 403)
        result = security.list_security_rejections(page=1, page_size=50, reason=None)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["reason"], "ip_not_allowed")
        self.assertEqual(result["items"][0]["query_string"], "probe=1")
        self.assertEqual(result["items"][0]["x_forwarded_for"], "203.0.113.9")

        security.put_cors(
            security.CorsPolicy(allowed_origins=["https://allowed.example"])
        )
        response = TestClient(app).options(
            "/v1/check",
            headers={
                "Origin": "https://blocked.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(response.status_code, 403)
        origins = security.list_security_rejections(
            page=1, page_size=50, reason="origin_not_allowed"
        )
        self.assertEqual(origins["total"], 1)
        self.assertEqual(origins["items"][0]["origin"], "https://blocked.example")

    def test_validation_failures_are_audited_without_query_credentials(self):
        app = FastAPI()
        app.add_middleware(RequestFailureAuditMiddleware)

        @app.get("/v1/items/{item_id}")
        def item(item_id: int):
            return {"item_id": item_id}

        response = TestClient(app).get(
            "/v1/items/not-an-int?token=secret-value&probe=1"
        )
        self.assertEqual(422, response.status_code)
        event = storage.row("SELECT * FROM request_failures ORDER BY id DESC LIMIT 1")
        self.assertEqual(422, event["status_code"])
        self.assertEqual("validation", event["phase"])
        self.assertEqual("validation_failed", event["reason"])
        self.assertEqual("token=[REDACTED]&probe=1", event["query_string"])

    def test_stream_emits_every_chunk_and_done_marker(self):
        models.add_model(
            CustomTextModelRequest(
                id="test-stream",
                display_name="Test Stream",
                download_url="https://example.com/stream.gguf",
                filename="stream.gguf",
            )
        )
        folder = storage.MODEL_DIR / "test-stream"
        folder.mkdir(parents=True)
        (folder / ".complete").touch()
        raw = {"id": "chatcmpl-test", "created": 1, "choices": [{"message": {"content": "الفب"}}]}
        app = FastAPI()
        app.include_router(openai_compat.router)
        queued = {"task_id": "chat-stream", "status": "succeeded", "result_json": json.dumps(raw)}
        with patch.dict("os.environ", {"ASR_API_KEY": "master"}), patch.object(
            openai_compat, "enqueue", return_value=(queued, True)
        ):
            response = TestClient(app).post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer master"},
                json={
                    "model": "test-stream",
                    "messages": [{"role": "user", "content": "سلام"}],
                    "stream": True,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.count("chat.completion.chunk"), 1)
        self.assertTrue(response.text.endswith("data: [DONE]\n\n"))

    def test_direct_chat_usage_is_in_per_model_statistics(self):
        storage.execute(
            "INSERT INTO usage(created_at,model_id,filename,status,processing_seconds,response_format) VALUES(?,?,?,'success',1.25,'json')",
            (storage.now(), "test-stat", "chat.completions"),
        )
        item = next(row for row in analytics.stats()["per_model"] if row["model_id"] == "test-stat")
        self.assertEqual(item["total"], 1)
        self.assertEqual(item["success"], 1)


if __name__ == "__main__":
    unittest.main()
