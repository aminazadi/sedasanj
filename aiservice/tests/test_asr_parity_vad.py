import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from asr_service.services.speech_segmentation import vad_regions

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "sedasanj"
    / "tests"
    / "fixtures"
    / "asr_parity"
    / "energy_vad.json"
)


def build_signal(case, sample_rate):
    n = int(round(case["duration_s"] * sample_rate))
    t = np.arange(n, dtype=np.float64) / sample_rate
    floor = case["floor"]
    signal = floor["amp"] * np.sin(2 * math.pi * floor["freq"] * t)
    for burst in case["bursts"]:
        mask = (t >= burst["start"]) & (t < burst["end"])
        signal[mask] += burst["amp"] * np.sin(2 * math.pi * burst["freq"] * t[mask])
    return signal.astype(np.float32)


class ParityEnergyVadTests(unittest.TestCase):
    """Server half of the energy-VAD parity vectors, also run by Jalase-Negar."""

    def test_vad_regions_match_shared_vectors(self):
        doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for case in doc["cases"]:
            with self.subTest(case["name"]), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "signal.wav"
                sf.write(path, build_signal(case, doc["sample_rate"]), doc["sample_rate"], subtype="FLOAT")
                regions = vad_regions(
                    path, min_seconds=doc["min_seconds"], padding_seconds=doc["padding_seconds"]
                )
                self.assertEqual(len(case["expected_regions"]), len(regions))
                for expected, region in zip(case["expected_regions"], regions):
                    self.assertAlmostEqual(expected[0], region.start, places=9)
                    self.assertAlmostEqual(expected[1], region.end, places=9)


if __name__ == "__main__":
    unittest.main()
