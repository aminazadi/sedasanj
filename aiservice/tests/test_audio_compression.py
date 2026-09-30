import gzip
import io
import unittest

from asr_service.services.audio_compression import GzipAudioError, decompress_gzip


class AudioCompressionTests(unittest.TestCase):
    def test_decompresses_gzip_and_reports_encoded_digest(self):
        payload = b"RIFF" + b"audio" * 100
        encoded = gzip.compress(payload)
        output = io.BytesIO()
        result = decompress_gzip(
            io.BytesIO(encoded), output, maximum_bytes=len(payload), expected_bytes=len(payload)
        )
        self.assertEqual(payload, output.getvalue())
        self.assertEqual(len(encoded), result["compressed_bytes"])
        self.assertEqual(len(payload), result["audio_bytes"])

    def test_rejects_invalid_gzip(self):
        with self.assertRaises(GzipAudioError):
            decompress_gzip(io.BytesIO(b"not-gzip"), io.BytesIO(), maximum_bytes=100)

    def test_rejects_expansion_beyond_limit(self):
        encoded = gzip.compress(b"x" * 1000)
        with self.assertRaisesRegex(GzipAudioError, "Uncompressed"):
            decompress_gzip(io.BytesIO(encoded), io.BytesIO(), maximum_bytes=100)

    def test_rejects_declared_size_mismatch(self):
        encoded = gzip.compress(b"audio")
        with self.assertRaisesRegex(GzipAudioError, "does not match"):
            decompress_gzip(io.BytesIO(encoded), io.BytesIO(), maximum_bytes=100, expected_bytes=6)
