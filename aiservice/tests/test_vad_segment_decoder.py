import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from asr_service.services import vad_segment_decoder as vsd


class VadSegmentDecoderTests(unittest.TestCase):
    def test_normalize_text_matches_app(self):
        fixture = Path(__file__).resolve().parents[2] / (
            "sedasanj/tests/fixtures/asr_parity/normalization.json"
        )
        for case in json.loads(fixture.read_text())["cases"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(
                    vsd.normalize_persian_asr_text(case["input"]),
                    case.get("app_today", case["server"]),
                )

    def _decode(self, audio, spans, decode, sample_rate=16000):
        class BlockVad:
            def spans(self, blocks):
                for _ in blocks:
                    pass
                for start, length in spans:
                    yield vsd.VadSpan(start, np.empty(length, dtype=np.float32))

        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "call.wav"
            sf.write(path, audio, sample_rate)
            return vsd.decode_file(path, BlockVad(), decode, lambda _msg: None)

    def test_quiet_audio_gain_and_silence(self):
        quiet = (np.sin(np.linspace(0, 200, 16000)) * 0.01).astype(np.float32)
        lifted = vsd.normalize_quiet_audio(quiet)
        self.assertGreater(float(np.abs(lifted).max()), float(np.abs(quiet).max()) * 5)
        silent = np.zeros(1000, dtype=np.float32)
        self.assertIs(vsd.normalize_quiet_audio(silent), silent)
        loud = (np.sin(np.linspace(0, 200, 16000)) * 0.5).astype(np.float32)
        self.assertIs(vsd.normalize_quiet_audio(loud), loud)

    def test_context_padded_with_silence_at_file_start(self):
        audio = np.ones(40000, dtype=np.float32)
        out = vsd.add_asr_context(audio, 4000, 8000)
        self.assertEqual(len(out), 12000 + 4000 + 12000)
        self.assertEqual(float(out[:8000].sum()), 0.0)
        out = vsd.add_asr_context(audio, 20000, 24000)
        self.assertEqual(len(out), 12000 + 4000 + 12000)

    def test_decodes_each_span_with_vad_timestamps(self):
        audio = np.full(160000, 0.2, dtype=np.float32)
        texts = iter(["سلام", "خداحافظ"])
        seg, duration = self._decode(
            audio, [(16000, 16000), (64000, 32000)], lambda _samples: next(texts)
        )
        self.assertEqual(duration, 10.0)
        self.assertEqual([s["text"] for s in seg], ["سلام", "خداحافظ"])
        self.assertEqual((seg[0]["start"], seg[0]["end"]), (1.0, 2.0))
        self.assertEqual((seg[1]["start"], seg[1]["end"]), (4.0, 6.0))
        self.assertTrue(all(s["timestamp_source"] == "silero_vad" for s in seg))

    def test_duplicates_and_empty_are_dropped(self):
        audio = np.full(160000, 0.2, dtype=np.float32)
        texts = iter(["سلام وقت بخیر", "", "سلام وقت بخیر"])
        seg, _ = self._decode(
            audio, [(0, 16000), (20000, 16000), (24000, 16000)], lambda _s: next(texts)
        )
        self.assertEqual(len(seg), 1)

    def test_no_text_raises(self):
        audio = np.full(32000, 0.2, dtype=np.float32)
        with self.assertRaises(vsd.NoVadSpeechError):
            self._decode(audio, [(0, 16000)], lambda _s: "")
        with self.assertRaises(vsd.NoVadSpeechError):
            self._decode(audio, [], lambda _s: "x")

    def test_resample(self):
        samples = []
        segments, duration = self._decode(
            np.ones(8000, dtype=np.float32) * 0.1,
            [(0, 8000)],
            lambda clip: samples.append(clip) or "سلام",
            sample_rate=8000,
        )
        self.assertEqual(duration, 1.0)
        self.assertEqual(segments[0]["end"], 0.5)
        self.assertEqual(len(samples[0]), 28000)
        self.assertTrue(np.all(samples[0][:12000] == samples[0][0]))
        self.assertGreater(float(samples[0][13000]), float(samples[0][0]))


if __name__ == "__main__":
    unittest.main()
