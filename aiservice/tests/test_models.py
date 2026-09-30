import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asr_service.domain.catalog import BUZZASR_REVISION, CATALOG, PERSIAN_V4_REVISION
from asr_service.services.model_builder import prepare_model


class CatalogTests(unittest.TestCase):
    def test_new_models_are_pinned_and_use_safetensors(self):
        for model_id, revision in (("whisper-persian-v4", PERSIAN_V4_REVISION), ("buzzasr-persian", BUZZASR_REVISION)):
            spec = CATALOG[model_id]
            self.assertEqual(spec.revision, revision)
            self.assertEqual(spec.preparation, "whisper_ct2_int8")
            self.assertTrue(all(f"/resolve/{revision}/" in item.url for item in spec.files))
            self.assertFalse(any(item.filename.endswith((".bin", ".pt", ".pth")) for item in spec.files))

    def test_weight_files_have_exact_size_and_sha256(self):
        for model_id in ("whisper-persian-v4", "buzzasr-persian"):
            weights = [item for item in CATALOG[model_id].files if item.filename.endswith(".safetensors")]
            self.assertTrue(weights)
            for item in weights:
                self.assertGreater(item.expected_size, 1_000_000_000)
                self.assertEqual(len(item.sha256), 64)
                self.assertFalse(item.size_is_estimate)

    def test_buzzasr_decoding_settings_are_preserved(self):
        decoding = CATALOG["buzzasr-persian"].decoding
        self.assertEqual(decoding["no_repeat_ngram_size"], 3)
        self.assertEqual(decoding["repetition_penalty"], 1.2)


class BuilderTests(unittest.TestCase):
    def test_conversion_replaces_source_only_after_validation(self):
        spec = CATALOG["buzzasr-persian"]
        statuses = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "model.safetensors").write_bytes(b"source")
            (root / "generation_config.json").write_text("{}")

            def fake_converter(command, env=None):
                if command[0] != "ct2-transformers-converter":
                    return
                output = root / ".converted"
                output.mkdir()
                for name in ("model.bin", "config.json", "tokenizer.json", "preprocessor_config.json"):
                    (output / name).write_bytes(b"converted")

            with patch("asr_service.services.model_builder._make_fast_tokenizer"), patch("asr_service.services.model_builder._run", side_effect=fake_converter), patch("asr_service.services.model_builder._validate_ctranslate2"):
                prepare_model(spec, root, statuses.append)

            self.assertEqual(statuses, ["preparing", "converting", "validating"])
            self.assertFalse((root / "model.safetensors").exists())
            self.assertTrue((root / "model.bin").exists())
            metadata = json.loads((root / "install_metadata.json").read_text())
            self.assertEqual(metadata["source_revision"], BUZZASR_REVISION)
            self.assertEqual(metadata["decoding"]["no_repeat_ngram_size"], 3)

    def test_failed_validation_keeps_source_for_retry(self):
        spec = CATALOG["buzzasr-persian"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "model.safetensors"
            source.write_bytes(b"source")
            (root / "generation_config.json").write_text("{}")

            def fake_converter(command, env=None):
                if command[0] == "ct2-transformers-converter":
                    (root / ".converted").mkdir()

            with patch("asr_service.services.model_builder._make_fast_tokenizer"), patch("asr_service.services.model_builder._run", side_effect=fake_converter), patch("asr_service.services.model_builder._validate_ctranslate2", side_effect=RuntimeError("invalid")):
                with self.assertRaisesRegex(RuntimeError, "invalid"):
                    prepare_model(spec, root)
            self.assertTrue(source.exists())


if __name__ == "__main__":
    unittest.main()
