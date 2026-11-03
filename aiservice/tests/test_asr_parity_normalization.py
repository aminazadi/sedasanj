import json
import unittest
from pathlib import Path

from asr_service.services import inference

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "sedasanj"
    / "tests"
    / "fixtures"
    / "asr_parity"
    / "normalization.json"
)


class ParityNormalizationTests(unittest.TestCase):
    """Server half of the ASR parity contract: shared vectors, also run by Jalase-Negar."""

    def test_server_normalize_matches_shared_vectors(self):
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
        self.assertGreater(len(cases), 5)
        for case in cases:
            with self.subTest(case["name"]):
                self.assertEqual(case["server"], inference.normalize(case["input"]))


if __name__ == "__main__":
    unittest.main()
