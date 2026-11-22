import importlib.util
import sys
import types
import unittest
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse


def _load_pages_module():
    """Import the router module without starting the full application."""

    if "requests" not in sys.modules and importlib.util.find_spec("requests") is None:
        requests = types.ModuleType("requests")
        requests.Session = object
        requests.HTTPError = type("HTTPError", (Exception,), {})
        requests.RequestException = type("RequestException", (Exception,), {})
        sys.modules["requests"] = requests
    from asr_service.api.routers import pages

    return pages


class AdminFontTests(unittest.TestCase):
    def test_serves_bundled_yekan_bakh_file(self) -> None:
        pages = _load_pages_module()
        response = pages.admin_font("YekanBakh-Regular.woff2")
        self.assertIsInstance(response, FileResponse)
        self.assertTrue(Path(response.path).is_file())
        self.assertEqual(response.media_type, "font/woff2")

    def test_rejects_arbitrary_file_names(self) -> None:
        pages = _load_pages_module()
        with self.assertRaises(HTTPException) as ctx:
            pages.admin_font("../../pyproject.toml")
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
