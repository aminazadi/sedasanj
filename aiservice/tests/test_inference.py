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
