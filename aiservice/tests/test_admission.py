import asyncio
import shutil
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from asr_service.api import admission
from asr_service.services import ingress


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_large_body_before_calling_application(self):
        application = AsyncMock()
        middleware = admission.IngressAdmissionMiddleware(application)
        messages = []

        async def send(message):
            messages.append(message)

        with patch.object(admission, "record_failure"):
            await middleware(
                {
                    "type": "http",
                    "path": "/v1/audio/transcriptions",
                    "headers": [
                        (b"content-length", str(admission.HTTP_MAX_BODY_BYTES + 1).encode())
                    ],
                },
                AsyncMock(),
                send,
            )

        application.assert_not_awaited()
        self.assertEqual(413, messages[0]["status"])

    async def test_rejects_when_all_http_slots_are_busy(self):
        application = AsyncMock()
        middleware = admission.IngressAdmissionMiddleware(application)
        middleware.slots = asyncio.Semaphore(0)
        messages = []

        async def send(message):
            messages.append(message)

        with patch.object(admission, "HTTP_ADMISSION_WAIT_SECONDS", 0.01), patch.object(
            admission, "record_failure"
        ):
            await middleware(
                {"type": "http", "path": "/v1/models", "headers": []},
                AsyncMock(),
                send,
            )

        application.assert_not_awaited()
        self.assertEqual(503, messages[0]["status"])


class SpoolCapacityTests(unittest.TestCase):
    def test_rejects_low_disk_headroom(self):
        usage = shutil._ntuple_diskusage(1000, 950, 50)
        with patch.object(ingress.shutil, "disk_usage", return_value=usage), patch.object(
            ingress, "SPOOL_MIN_FREE_BYTES", 100
        ), patch.object(ingress, "SPOOL_MIN_FREE_PERCENT", 10):
            with self.assertRaises(ingress.UploadCapacityError):
                ingress.ensure_spool_capacity(MagicMock())

    def test_rejects_weighted_audio_capacity(self):
        usage = shutil._ntuple_diskusage(10_000, 1000, 9000)
        with patch.object(ingress.shutil, "disk_usage", return_value=usage), patch.object(
            ingress, "SPOOL_MIN_FREE_BYTES", 1
        ), patch.object(ingress, "SPOOL_MIN_FREE_PERCENT", 1), patch.object(
            ingress, "SPOOL_MAX_BYTES", 100
        ), patch.object(ingress, "row", return_value={"bytes": 90}):
            with self.assertRaises(ingress.UploadCapacityError):
                ingress.ensure_spool_capacity(MagicMock(), 11)
