"""Contract tests for direct S3-compatible upload sessions."""

import tempfile
import unittest
import gzip
import io
from pathlib import Path
from unittest.mock import patch

from asr_service.api.dependencies import Principal
from asr_service.api.routers import tasks
from asr_service.api.schemas.uploads import UploadCompleteRequest, UploadCreateRequest
from asr_service.infrastructure import storage


class DirectUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [
            patch.object(storage, "DATA_DIR", root),
            patch.object(storage, "MODEL_DIR", root / "models"),
            patch.object(storage, "DB_PATH", root / "asr.sqlite3"),
            patch.object(tasks.object_storage, "PART_SIZE", 5 * 1024 * 1024),
            patch.object(tasks.object_storage, "enabled", return_value=True),
            patch.object(tasks.object_storage, "create_multipart", return_value="backend-upload"),
            patch.object(tasks.object_storage, "part_url", return_value="https://uploads.example/part"),
            patch.object(tasks.object_storage, "complete_multipart", return_value={}),
            patch.object(tasks.object_storage, "head", return_value={"ContentLength": 6 * 1024 * 1024}),
        ]
        for item in self.patches:
            item.start()
        storage.init_db()
        self.principal = Principal(is_admin=True)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_direct_multipart_lifecycle_validates_all_parts_and_size(self):
        created = tasks.create_upload(
            UploadCreateRequest(filename="جلسه.mp3", audio_bytes=6 * 1024 * 1024),
            self.principal,
        )
        self.assertEqual("uploading", created["status"])
        self.assertEqual(5 * 1024 * 1024, created["part_size"])
        upload_id = created["upload_id"]

        url = tasks.upload_part_url(upload_id, 2, self.principal)
        self.assertEqual("https://uploads.example/part", url["url"])

        completed = tasks.complete_upload(
            upload_id,
            UploadCompleteRequest(parts=[
                {"part_number": 1, "etag": '"part-1"'},
                {"part_number": 2, "etag": '"part-2"'},
            ]),
            self.principal,
        )
        self.assertEqual("completed", completed["status"])
        self.assertEqual(6 * 1024 * 1024, completed["actual_bytes"])

    def test_direct_multipart_rejects_missing_part(self):
        created = tasks.create_upload(
            UploadCreateRequest(filename="audio.wav", audio_bytes=6 * 1024 * 1024),
            self.principal,
        )
        with self.assertRaises(tasks.HTTPException) as error:
            tasks.complete_upload(
                created["upload_id"],
                UploadCompleteRequest(parts=[{"part_number": 1, "etag": '"part-1"'}]),
                self.principal,
            )
        self.assertEqual(400, error.exception.status_code)

    def test_gzip_upload_requires_decoded_size_and_is_validated_before_completion(self):
        with self.assertRaises(ValueError):
            UploadCreateRequest(filename="audio.wav", audio_bytes=10, audio_encoding="gzip")
        payload = b"RIFF" + b"audio" * 20
        encoded = gzip.compress(payload)
        with patch.object(tasks.object_storage, "head", return_value={"ContentLength": len(encoded)}), patch.object(tasks.object_storage, "open_object", return_value=io.BytesIO(encoded)):
            created = tasks.create_upload(
                UploadCreateRequest(filename="audio.wav", audio_bytes=len(encoded), audio_encoding="gzip", uncompressed_audio_bytes=len(payload)),
                self.principal,
            )
            completed = tasks.complete_upload(
                created["upload_id"], UploadCompleteRequest(parts=[{"part_number": 1, "etag": '"part-1"'}]), self.principal
            )
        self.assertEqual("gzip", completed["audio_encoding"])
        self.assertEqual(len(payload), completed["uncompressed_audio_bytes"])
