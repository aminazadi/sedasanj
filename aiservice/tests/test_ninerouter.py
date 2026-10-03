import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from fastapi import HTTPException

from asr_service.api.routers import ninerouter as ninerouter_router
from asr_service.api.routers import tasks
from asr_service.domain.catalog import CATALOG
from asr_service.infrastructure import ninerouter, storage


class NineRouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_data_dir = storage.DATA_DIR
        self.previous_model_dir = storage.MODEL_DIR
        self.previous_path = storage.DB_PATH
        storage.DATA_DIR = Path(self.tmp.name)
        storage.MODEL_DIR = Path(self.tmp.name) / "models"
        storage.DB_PATH = Path(self.tmp.name) / "test.sqlite3"
        storage.init_db()
        self.environment = patch.dict(os.environ, {"ASR_9ROUTER_SECRETS_KEY": Fernet.generate_key().decode()})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        storage.DATA_DIR = self.previous_data_dir
        storage.MODEL_DIR = self.previous_model_dir
        storage.DB_PATH = self.previous_path
        self.tmp.cleanup()

    def test_url_normalization_and_secret_redaction(self):
        saved = ninerouter.save_config({
            "url": "http://127.0.0.1:20128/v1/", "api_key": "secret-value",
            "asr_enabled": True, "asr_model": "stt/model", "text_enabled": False,
            "text_model": "", "connect_timeout_seconds": 10, "read_timeout_seconds": 300,
        })
        self.assertEqual(saved["url"], "http://127.0.0.1:20128")
        self.assertTrue(saved["has_api_key"])
        self.assertNotIn("api_key", saved.keys())
        raw = storage.row("SELECT value FROM settings WHERE key=?", (ninerouter.SETTING_KEY,))["value"]
        self.assertNotIn("secret-value", raw)
        self.assertEqual(ninerouter.resolve_settings().api_key, "secret-value")

    def test_invalid_url_and_missing_key_are_rejected(self):
        with self.assertRaises(ValueError):
            ninerouter.normalize_url("https://user:pass@example.test")
        with self.assertRaises(ninerouter.NineRouterError):
            ninerouter.save_config({"url": "https://router.example", "api_key": None, "asr_enabled": True, "asr_model": "x", "text_enabled": False, "text_model": "", "connect_timeout_seconds": 10, "read_timeout_seconds": 300})

    def test_retry_classification_and_model_discovery(self):
        settings = ninerouter.ProviderSettings("https://router.example", "key", False, "", False, "", (1, 1))
        response = Mock(status_code=503, text="upstream down")
        response.json.return_value = {"error": "upstream down"}
        with patch("asr_service.infrastructure.ninerouter.requests.request", return_value=response):
            with self.assertRaises(ninerouter.NineRouterError) as caught:
                ninerouter.NineRouterClient(settings).models("chat")
        self.assertTrue(caught.exception.retryable)
        response.status_code = 401
        with patch("asr_service.infrastructure.ninerouter.requests.request", return_value=response):
            with self.assertRaises(ninerouter.NineRouterError) as caught:
                ninerouter.NineRouterClient(settings).models("stt")
        self.assertFalse(caught.exception.retryable)

    def test_transcription_without_segments_is_normalized(self):
        settings = ninerouter.ProviderSettings("https://router.example", "key", False, "", False, "", (1, 1))
        response = Mock(status_code=200)
        response.json.return_value = {"text": "سلام", "duration": 3.5}
        audio = Path(self.tmp.name) / "audio.wav"
        audio.write_bytes(b"audio")
        with patch(
            "asr_service.infrastructure.ninerouter.requests.request",
            return_value=response,
        ) as request:
            result = ninerouter.NineRouterClient(settings).transcribe("stt/model", audio)
        self.assertEqual(result["segments"], [])
        self.assertEqual(
            request.call_args.kwargs["data"]["response_format"], "verbose_json"
        )

    def test_transcription_prompt_is_forwarded(self):
        settings = ninerouter.ProviderSettings(
            "https://router.example", "key", False, "", False, "", (1, 1)
        )
        response = Mock(status_code=200)
        response.json.return_value = {"text": "سلام", "duration": 1.0}
        audio = Path(self.tmp.name) / "audio.wav"
        audio.write_bytes(b"audio")
        with patch(
            "asr_service.infrastructure.ninerouter.requests.request",
            return_value=response,
        ) as request:
            ninerouter.NineRouterClient(settings).transcribe(
                "stt/model", audio, "واژگان تخصصی را حفظ کن"
            )
        self.assertEqual(
            request.call_args.kwargs["data"]["prompt"],
            "واژگان تخصصی را حفظ کن",
        )

    def test_gpt_4o_transcription_models_use_json_response_format(self):
        settings = ninerouter.ProviderSettings(
            "https://router.example", "key", False, "", False, "", (1, 1)
        )
        response = Mock(status_code=200)
        response.json.return_value = {"text": "سلام"}
        audio = Path(self.tmp.name) / "audio.wav"
        audio.write_bytes(b"audio")
        for model in (
            "openai/gpt-4o-transcribe",
            "openai/gpt-4o-mini-transcribe",
        ):
            with self.subTest(model=model), patch(
                "asr_service.infrastructure.ninerouter.requests.request",
                return_value=response,
            ) as request:
                result = ninerouter.NineRouterClient(settings).transcribe(model, audio)
            self.assertEqual(
                request.call_args.kwargs["data"]["response_format"], "json"
            )
            self.assertEqual(result["segments"], [])

    def test_versioned_gpt_4o_transcription_uses_json_response_format(self):
        settings = ninerouter.ProviderSettings(
            "https://router.example", "key", False, "", False, "", (1, 1)
        )
        response = Mock(status_code=200)
        response.json.return_value = {"text": "سلام"}
        audio = Path(self.tmp.name) / "audio.wav"
        audio.write_bytes(b"audio")
        with patch(
            "asr_service.infrastructure.ninerouter.requests.request",
            return_value=response,
        ) as request:
            ninerouter.NineRouterClient(settings).transcribe(
                "openai/gpt-4o-transcribe-api-eV3", audio
            )
        self.assertEqual(request.call_args.kwargs["data"]["response_format"], "json")

    def test_all_cached_asr_models_are_executable_when_provider_is_enabled(self):
        ninerouter.save_models(
            [
                {"id": "openai/gpt-4o-transcribe", "kind": "asr"},
                {"id": "openai/whisper-1", "kind": "asr"},
            ]
        )
        ninerouter.save_config(
            {
                "url": "https://router.example",
                "api_key": "secret-value",
                "asr_enabled": True,
                "asr_model": "openai/gpt-4o-transcribe",
                "text_enabled": False,
                "text_model": "",
                "connect_timeout_seconds": 10,
                "read_timeout_seconds": 300,
            }
        )

        self.assertEqual(
            {"openai/gpt-4o-transcribe", "openai/whisper-1"},
            ninerouter.configured_models("asr"),
        )

    def test_openai_chat_completions_proxy_path_is_allowed(self):
        self.assertIn("chat/completions", ninerouter_router.ALLOWED_PATHS)

    def test_local_and_remote_models_remain_independently_routable(self):
        model_dir = Path(self.tmp.name) / "models"
        for model_id in ("whisper-large-v3", "dorna-8b-q4_k_m"):
            (model_dir / model_id).mkdir(parents=True)
            (model_dir / model_id / ".complete").touch()

        configured = {
            "asr": {"openai/gpt-4o-transcribe", "openai/whisper-1"},
            "llm": {"codex-three-accounts"},
        }
        with (
            patch.object(tasks, "MODEL_DIR", model_dir),
            patch.object(tasks, "configured_models", side_effect=configured.get),
        ):
            self.assertEqual(
                tasks.ordered_models("whisper-large-v3", None, "asr"),
                ["whisper-large-v3"],
            )
            self.assertEqual(
                tasks.ordered_models("openai/gpt-4o-transcribe", None, "asr"),
                ["openai/gpt-4o-transcribe"],
            )
            self.assertEqual(
                tasks.ordered_models("openai/whisper-1", None, "asr"),
                ["openai/whisper-1"],
            )
            self.assertEqual(
                tasks.ordered_models("dorna-8b-q4_k_m", None, "llm"),
                ["dorna-8b-q4_k_m"],
            )
            self.assertEqual(
                tasks.ordered_models("codex-three-accounts", None, "llm"),
                ["codex-three-accounts"],
            )
            with self.assertRaises(HTTPException) as caught:
                tasks.ordered_models("unknown-model", None, "asr")

        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("unknown-model", caught.exception.detail)
        self.assertIn("whisper-large-v3", CATALOG)
