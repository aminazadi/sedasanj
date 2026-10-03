import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from asr_service.infrastructure.ninerouter import NineRouterEmptyTranscriptionError
from asr_service.services.speech_segmentation import (
    normalize_transcription,
    vad_regions,
)


class SpeechSegmentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "speech.wav"
        sample_rate = 16000
        audio = np.zeros(sample_rate * 4, dtype=np.float32)
        tone = 0.25 * np.sin(2 * np.pi * 220 * np.arange(sample_rate) / sample_rate)
        audio[:sample_rate] = tone
        audio[sample_rate * 2 : sample_rate * 3] = tone
        sf.write(self.path, audio, sample_rate)

    def tearDown(self):
        self.temp.cleanup()

    def test_vad_separates_speech_around_long_silence(self):
        regions = vad_regions(self.path, min_seconds=0.2, padding_seconds=0.05)
        self.assertEqual(len(regions), 2)
        self.assertLess(regions[0].end, regions[1].start)

    def test_text_only_result_is_recovered_as_timestamped_turns(self):
        calls = []

        def decode(path):
            calls.append(path)
            return {"text": "سلام", "segments": [], "duration": 1.0}

        result = normalize_transcription(
            self.path,
            {"text": "متن یکپارچه", "segments": [], "duration": 4.0},
            decode,
            ensure_timestamps=True,
            diarize=False,
            min_seconds=0.2,
            padding_seconds=0.05,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result["segments"]), 2)
        self.assertTrue(all(row["timestamp_source"] == "vad_window" for row in result["segments"]))
        self.assertTrue(all(row["end"] > row["start"] for row in result["segments"]))

    def test_long_full_duration_segment_is_recovered_from_vad(self):
        sample_rate = 16000
        path = Path(self.temp.name) / "long-speech.wav"
        audio = np.zeros(sample_rate * 10, dtype=np.float32)
        tone = 0.25 * np.sin(2 * np.pi * 220 * np.arange(sample_rate) / sample_rate)
        audio[:sample_rate] = tone
        audio[sample_rate * 5 : sample_rate * 6] = tone
        sf.write(path, audio, sample_rate)

        def decode(_path):
            return {"text": "بخش", "segments": [], "duration": 1.0}

        result = normalize_transcription(
            path,
            {
                "text": "متن ساختگی",
                "segments": [{"text": "متن ساختگی", "start": 0.0, "end": 10.0}],
                "duration": 10.0,
            },
            decode,
            ensure_timestamps=True,
            diarize=False,
            min_seconds=0.2,
            padding_seconds=0.05,
        )

        self.assertEqual(len(result["segments"]), 2)
        self.assertTrue(all(row["timestamp_source"] == "vad_window" for row in result["segments"]))

    def test_empty_provider_region_does_not_discard_other_speech_regions(self):
        calls = 0

        def decode(_path):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise NineRouterEmptyTranscriptionError("empty", retryable=False)
            return {"text": "بخش دوم", "segments": [], "duration": 1.0}

        result = normalize_transcription(
            self.path,
            {"text": "", "segments": [], "duration": 4.0},
            decode,
            ensure_timestamps=True,
            diarize=False,
            min_seconds=0.2,
            padding_seconds=0.05,
        )

        self.assertEqual(result["text"], "بخش دوم")
        self.assertEqual(len(result["segments"]), 1)


if __name__ == "__main__":
    unittest.main()
