import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet

from asr_service.infrastructure import storage
from asr_service.infrastructure import ninerouter


class NineRouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_path = storage.DB_PATH
        storage.DB_PATH = Path(self.tmp.name) / "test.sqlite3"
        storage.init_db()
        self.environment = patch.dict(os.environ, {"ASR_9ROUTER_SECRETS_KEY": Fernet.generate_key().decode()})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
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
        with patch("asr_service.infrastructure.ninerouter.requests.request", return_value=response):
            result = ninerouter.NineRouterClient(settings).transcribe("stt/model", audio)
        self.assertEqual(result["segments"], [{"id": 0, "start": 0, "end": 3.5, "text": "سلام"}])
