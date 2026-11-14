import os
import sys
import tempfile
import unittest
import io
from pathlib import Path
from unittest.mock import Mock, patch

from asr_service.services import inference


class InferenceTests(unittest.TestCase):
    def test_faster_whisper_receives_string_path(self):
        engine = Mock()
        info = Mock(duration=1.0, duration_after_vad=1.0)
        engine.transcribe.return_value = (
            iter((Mock(start=0.0, end=1.0, text="سلام"),)), info
        )
        with tempfile.NamedTemporaryFile(suffix=".mp3") as audio:
            with patch.dict(sys.modules, {"soundfile": Mock()}), patch.object(
                inference, "load", return_value=engine
            ), patch.object(
                inference, "MODEL_DIR", Path(audio.name).parent / "missing-models"
            ):
                inference.transcribe(Path(audio.name), "buzzasr-persian", 5, True, None)
        supplied = engine.transcribe.call_args.args[0]
        self.assertIsInstance(supplied, str)
        self.assertEqual(audio.name, supplied)

    def _silero_models(self, root, model_id):
        (root / "silero-vad").mkdir(parents=True)
        (root / "silero-vad" / "silero_vad.onnx").touch()
        (root / model_id).mkdir()
        (root / model_id / ".complete").touch()

    def test_silero_architectures_split_cpu_only_from_whisper(self):
        for model_id in ("shenava-koochik-v1-5-rnnt", "shenava-rizeh"):
            self.assertTrue(inference.supports_silero(model_id))
            self.assertTrue(inference.silero_cpu_only(model_id))
        for model_id in ("whisper-large-v3", "whisper-persian-v4", "buzzasr-persian"):
            self.assertTrue(inference.supports_silero(model_id))
            self.assertFalse(inference.silero_cpu_only(model_id))
        for model_id in ("silero-vad", "dorna-8b-q4_k_m", "unknown-model"):
            self.assertFalse(inference.supports_silero(model_id))
            self.assertFalse(inference.silero_cpu_only(model_id))

    def test_whisper_decodes_each_silero_span_without_inner_vad(self):
        import numpy as np
        from asr_service.services import vad_segment_decoder as vsd

        engine = Mock()
        engine.transcribe.return_value = (
            iter((
                Mock(text="سلام", avg_logprob=-0.2, no_speech_prob=0.1, compression_ratio=1.1),
                Mock(text="دوست من", avg_logprob=-0.4, no_speech_prob=0.3, compression_ratio=1.3),
            )),
            Mock(),
        )
        seen = {}

        def fake_decode_file(path, vad, decode, on_event):
            seen["result"] = decode(np.zeros(16000, dtype=np.float32))
            return [{"id": 0, "start": 0.0, "end": 1.0, "text": "x",
                     "timestamp_source": "silero_vad"}], 1.0

        with tempfile.TemporaryDirectory() as root, tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            self._silero_models(Path(root), "buzzasr-persian")
            with patch.object(inference, "MODEL_DIR", Path(root)), patch.object(
                inference, "load", return_value=engine
            ) as load, patch.object(vsd, "decode_file", side_effect=fake_decode_file):
                inference.transcribe(
                    Path(audio.name), "buzzasr-persian", 4, True, "پرامپت", segmenter="silero_vad"
                )
        load.assert_called_once_with("buzzasr-persian")
        options = engine.transcribe.call_args.kwargs
        self.assertFalse(options["vad_filter"])
        self.assertFalse(options["condition_on_previous_text"])
        self.assertEqual((options["beam_size"], options["initial_prompt"]), (4, "پرامپت"))
        self.assertEqual((options["language"], options["task"]), ("fa", "transcribe"))
        # Model-specific decoding options from the catalog still apply (BuzzASR).
        self.assertEqual(options["repetition_penalty"], 1.2)
        text, stats = seen["result"]
        self.assertEqual(text, "سلام دوست من")
        self.assertAlmostEqual(stats["avg_logprob"], -0.3)
        self.assertEqual((stats["no_speech_prob"], stats["compression_ratio"]), (0.3, 1.3))

    def test_whisper_span_without_text_returns_empty(self):
        engine = Mock()
        engine.transcribe.return_value = (iter((Mock(text="  "),)), Mock())
        decode = inference._whisper_span_decoder(
            engine, "buzzasr-persian", inference.CATALOG["buzzasr-persian"], 2, None
        )
        self.assertEqual(decode(Mock()), "")

    def test_sherpa_silero_path_still_uses_cpu_engine_cache(self):
        import numpy as np
        from asr_service.services import vad_segment_decoder as vsd

        stream = Mock()
        stream.result.text = "سلام"
        engine = Mock()
        engine.create_stream.return_value = stream

        def fake_decode_file(path, vad, decode, on_event):
            self.assertEqual(decode(np.zeros(160, dtype=np.float32)), "سلام")
            return [{"id": 0, "start": 0.0, "end": 1.0, "text": "سلام",
                     "timestamp_source": "silero_vad"}], 1.0

        with tempfile.TemporaryDirectory() as root, tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            self._silero_models(Path(root), "shenava-koochik-v1-5-rnnt")
            with patch.object(inference, "MODEL_DIR", Path(root)), patch.object(
                inference, "_load", return_value=engine
            ) as load, patch.object(vsd, "decode_file", side_effect=fake_decode_file):
                inference.transcribe(
                    Path(audio.name), "shenava-koochik-v1-5-rnnt", 2, True, None,
                    segmenter="silero_vad",
                )
        load.assert_called_once_with("shenava-koochik-v1-5-rnnt", None)

    def test_denoised_samples_are_passed_as_readable_audio(self):
        engine = Mock()
        info = Mock(duration=1.0, duration_after_vad=1.0)
        speech = Mock(start=0.0, end=1.0, text="سلام")
        engine.transcribe.side_effect = [
            (iter(()), info),
            (iter(()), info),
            (iter((speech,)), info),
        ]
        enhanced = Mock(samples=[0.0, 0.25, -0.25], sample_rate=48000)
        fake_denoiser = Mock(return_value=enhanced)
        soundfile = Mock()

        def write_wav(buffer, samples, sample_rate, **kwargs):
            self.assertEqual(sample_rate, 48000)
            self.assertEqual(samples, [0.0, 0.25, -0.25])
            buffer.write(b"wav")

        soundfile.read.return_value = (Mock(mean=Mock(return_value=[0.0])), 48000)
        soundfile.write.side_effect = write_wav
        with tempfile.NamedTemporaryFile(suffix=".mp3") as audio:
            with patch.dict(os.environ, {"ASR_ENABLE_DENOISER": "1"}), patch.dict(sys.modules, {"soundfile": soundfile}), patch.object(
                inference, "load", return_value=engine
            ), patch.object(inference, "denoiser", return_value=fake_denoiser), patch.object(
                inference, "MODEL_DIR", Path(audio.name).parent
            ):
                (Path(audio.name).parent / "gtcrn-denoiser").mkdir(exist_ok=True)
                marker = Path(audio.name).parent / "gtcrn-denoiser" / ".complete"
                marker.touch()
                try:
                    inference.transcribe(
                        Path(audio.name), "buzzasr-persian", 5, True, None
                    )
                finally:
                    marker.unlink(missing_ok=True)
                    marker.parent.rmdir()

        supplied = engine.transcribe.call_args.args[0]
        self.assertIsInstance(supplied, io.BytesIO)
        self.assertTrue(supplied.readable())
        self.assertEqual(supplied.getvalue(), b"wav")

    def test_empty_vad_result_retries_original_audio_without_vad(self):
        engine = Mock()
        info = Mock(duration=1.0, duration_after_vad=0.8)
        spoken = Mock(start=0.0, end=0.8, text=" سلام ")
        engine.transcribe.side_effect = [(iter(()), info), (iter((spoken,)), info)]
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            with patch.dict(sys.modules, {"soundfile": Mock()}), patch.object(
                inference, "load", return_value=engine
            ), patch.object(inference, "MODEL_DIR", Path(audio.name).parent / "missing-models"):
                text, segments, _, _ = inference.transcribe(
                    Path(audio.name), "buzzasr-persian", 2, True, None
                )
        self.assertEqual(text, "سلام")
        self.assertEqual(len(segments), 1)
        self.assertEqual(engine.transcribe.call_count, 2)
        self.assertTrue(engine.transcribe.call_args_list[0].kwargs["vad_filter"])
        self.assertFalse(engine.transcribe.call_args_list[1].kwargs["vad_filter"])

    def test_empty_original_audio_is_not_reported_as_success(self):
        engine = Mock()
        info = Mock(duration=1.0, duration_after_vad=0.0)
        engine.transcribe.return_value = (iter(()), info)
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            with patch.dict(sys.modules, {"soundfile": Mock()}), patch.object(
                inference, "load", return_value=engine
            ), patch.object(inference, "MODEL_DIR", Path(audio.name).parent / "missing-models"):
                with self.assertRaises(inference.NoSpeechDetectedError):
                    inference.transcribe(Path(audio.name), "buzzasr-persian", 2, True, None)
        self.assertEqual(engine.transcribe.call_count, 2)


if __name__ == "__main__":
    unittest.main()
