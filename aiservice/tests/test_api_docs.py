import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_app():
    """Load the ASGI app in lightweight developer environments without requests."""

    if "requests" not in sys.modules and importlib.util.find_spec("requests") is None:
        requests = types.ModuleType("requests")
        requests.Session = object
        requests.HTTPError = type("HTTPError", (Exception,), {})
        requests.RequestException = type("RequestException", (Exception,), {})
        sys.modules["requests"] = requests
    from app import app

    return app


class ApiDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _load_app()
        endpoint = next(
            route for route in cls.app.routes if route.path == "/openapi/user.json"
        ).endpoint
        cls.user_schema_endpoint = staticmethod(endpoint)
        cls.user_schema = endpoint()
        cls.admin_schema = next(
            route for route in cls.app.routes if route.path == "/openapi/admin.json"
        ).endpoint()

    def test_documentation_routes_are_enabled(self):
        paths = {route.path for route in self.app.routes}
        expected = {
            "/docs",
            "/redoc",
            "/redoc/user",
            "/redoc/admin",
            "/openapi.json",
            "/openapi/user.json",
            "/openapi/admin.json",
        }
        self.assertTrue(expected.issubset(paths))

    def test_user_and_admin_documents_are_separated(self):
        user_paths = set(self.user_schema["paths"])
        admin_paths = set(self.admin_schema["paths"])
        self.assertIn("/health", user_paths)
        self.assertIn("/health", admin_paths)
        self.assertTrue(
            all(path == "/health" or path.startswith("/v1/") for path in user_paths)
        )
        self.assertTrue(
            all(path == "/health" or path.startswith("/api/") for path in admin_paths)
        )
        self.assertNotIn("/api/models", user_paths)
        self.assertNotIn("/v1/audio/transcriptions", admin_paths)

    def test_every_operation_has_english_documentation_and_typed_responses(self):
        for schema in (self.user_schema, self.admin_schema):
            for path_item in schema["paths"].values():
                for method, operation in path_item.items():
                    if method not in {"get", "post", "put", "delete", "patch"}:
                        continue
                    self.assertTrue(operation.get("summary"))
                    self.assertTrue(operation.get("description"))
                    for status_code, response in operation["responses"].items():
                        self.assertTrue(response.get("description"))
                        if status_code == "204":
                            continue
                        self.assertTrue(
                            response.get("content"),
                            f"Undocumented response body for {method}",
                        )

    def test_openapi_references_resolve(self):
        for schema in (self.user_schema, self.admin_schema):
            references = []

            def visit(value):
                if isinstance(value, dict):
                    if "$ref" in value:
                        references.append(value["$ref"])
                    for child in value.values():
                        visit(child)
                elif isinstance(value, list):
                    for child in value:
                        visit(child)

            visit(schema)
            available = set(schema.get("components", {}).get("schemas", {}))
            referenced = {
                ref.rsplit("/", 1)[-1]
                for ref in references
                if ref.startswith("#/components/schemas/")
            }
            self.assertFalse(referenced - available)

    def test_dashboard_links_to_both_redoc_documents(self):
        from asr_service.web.dashboard import HTML

        self.assertIn("/redoc/user", HTML)
        self.assertIn("/redoc/admin", HTML)

    def test_dashboard_displays_live_vps_resources(self):
        from asr_service.web.dashboard import HTML

        self.assertIn('id="resourceGrid"', HTML)
        self.assertIn('id="topProcesses"', HTML)
        self.assertIn("/api/system-metrics", HTML)
        self.assertIn("function renderSystem(", HTML)
        self.assertIn("CPU کانتینر", HTML)

        metrics = self.admin_schema["components"]["schemas"]["SystemMetricsResponse"]
        self.assertIn("scope", metrics["properties"])
        self.assertIn("container", metrics["properties"])

    def test_dashboard_handles_unavailable_clipboard_when_creating_key(self):
        from asr_service.web.dashboard import HTML

        self.assertIn("navigator.clipboard?.writeText", HTML)
        self.assertIn("let copied=await copyText(r.api_key);prompt(", HTML)
        self.assertNotIn("await navigator.clipboard.writeText(r.api_key)", HTML)

    def test_dashboard_can_delete_api_keys(self):
        from asr_service.web.dashboard import HTML

        self.assertIn("function deleteApiKey(", HTML)
        self.assertIn("method:'DELETE'", HTML)
        self.assertIn("r.status===204?null:r.json()", HTML)

    def test_api_keys_have_a_dedicated_page_and_creation_dialog(self):
        from asr_service.api.routers.pages import admin_keys
        from asr_service.web.dashboard import render_admin_page

        page = render_admin_page("keys")
        self.assertEqual(admin_keys(), page)
        self.assertIn('id="keysView"', page)
        self.assertNotIn('id="settingsView"', page)
        self.assertNotIn('id="dashboardView"', page)
        self.assertIn("location.pathname==='/admin/keys'", page)
        self.assertIn('id="createKeyModal"', page)
        self.assertIn('onsubmit="createApiKey(event)"', page)
        self.assertIn('id="apiKeys"', page)

    def test_admin_routes_render_only_the_requested_view(self):
        from asr_service.web.dashboard import render_admin_page

        views = {
            "dashboard": "dashboardView",
            "models": "modelsView",
            "usage": "usageView",
            "security": "securityView",
            "keys": "keysView",
            "settings": "settingsView",
        }
        for view, element in views.items():
            page = render_admin_page(view)
            self.assertIn(f'id="{element}"', page)
            if view != "dashboard":
                self.assertIn(f'id="{element}" class="settings active"', page)
            for other in set(views.values()) - {element}:
                self.assertNotIn(f'id="{other}"', page)

        dashboard = render_admin_page("dashboard")
        self.assertNotIn("renderSystem(sys);renderModels();", dashboard)
        self.assertNotIn("Promise.all([refresh(),loadUsage()])", dashboard)

    def test_admin_branding_uses_sooyab_name_without_the_old_logo(self):
        from asr_service.web.dashboard import render_admin_page

        for view in ("dashboard", "models", "usage", "security", "keys", "settings"):
            page = render_admin_page(view)
            self.assertIn("سرویس هوش مصنوعی سویاب", page)
            self.assertNotIn("کنسول مدیریت آوا", page)
            self.assertNotIn('<div class="logo">', page)

    def test_multi_model_contract_is_documented(self):
        transcription = self.user_schema["paths"]["/v1/audio/transcriptions"]["post"]
        request_schema = transcription["requestBody"]["content"]["multipart/form-data"][
            "schema"
        ]
        if "$ref" in request_schema:
            request_schema = self.user_schema["components"]["schemas"][
                request_schema["$ref"].rsplit("/", 1)[-1]
            ]
        self.assertIn("model", request_schema["properties"])
        self.assertIn("models", request_schema["properties"])

    def test_direct_upload_contract_has_typed_requests_and_responses(self):
        paths = self.user_schema["paths"]
        create = paths["/v1/uploads"]["post"]
        complete = paths["/v1/uploads/{upload_id}/complete"]["post"]
        schedule = paths["/v1/uploads/{upload_id}/transcriptions"]["post"]
        part = paths["/v1/uploads/{upload_id}/parts/{part_number}"]["post"]
        self.assertIn("$ref", create["requestBody"]["content"]["application/json"]["schema"])
        self.assertIn("UploadResponse", str(create["responses"]["201"]))
        self.assertIn("UploadPartUrlResponse", str(part["responses"]["200"]))
        self.assertIn("$ref", complete["requestBody"]["content"]["application/json"]["schema"])
        self.assertIn("TaskResponse", str(schedule["responses"]["202"]))
        task_schema = self.user_schema["components"]["schemas"]["TaskResponse"]
        for field in ("models", "current_model", "completed_models", "total_models"):
            self.assertIn(field, task_schema["properties"])

    def test_history_accordion_remains_inside_table(self):
        from asr_service.web.dashboard import HTML

        usage_body = HTML.index('id="usage"')
        table_start = HTML.rfind("<table>", 0, usage_body)
        table_end = HTML.index("</table>", usage_body)
        self.assertTrue(table_start < usage_body < table_end)
        self.assertIn('class="details-row"', HTML)
        self.assertIn("/api/usage/", HTML)

    def test_dashboard_shows_all_active_requests_without_pagination(self):
        from asr_service.web.dashboard import HTML

        self.assertIn('id="activeRequestsSection"', HTML)
        self.assertNotIn('id="activePageInfo"', HTML)
        self.assertIn("active=true&page=1&page_size=100", HTML)
        self.assertIn("activePage<=pages", HTML)

    def test_history_can_open_processed_output_as_markdown_dialog(self):
        from asr_service.web.dashboard import HTML

        self.assertIn('id="resultModal"', HTML)
        self.assertIn("function showResult", HTML)
        self.assertIn("function markdown", HTML)

    def test_failure_dashboard_uses_the_unified_failure_endpoint(self):
        from asr_service.web.dashboard import HTML

        self.assertIn("/api/request-failures", HTML)
        self.assertIn("رخدادهای ناموفق", HTML)
        self.assertIn("Task / Usage", HTML)

    def test_user_document_lists_only_installed_model_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            for model_id in ("shenava-rizeh", "dorna-8b-q3_k_m"):
                folder = model_dir / model_id
                folder.mkdir()
                (folder / ".complete").touch()

            with patch("asr_service.api.application.storage.MODEL_DIR", model_dir):
                schema = self.user_schema_endpoint()

        description = schema["info"]["description"]
        self.assertIn("`shenava-rizeh`", description)
        self.assertIn("`dorna-8b-q3_k_m`", description)
        self.assertNotIn("`whisper-large-v3`", description)

        components = schema["components"]["schemas"]
        transcription = components["Body_transcription_v1_audio_transcriptions_post"]
        self.assertEqual(
            transcription["properties"]["model"]["enum"], ["shenava-rizeh"]
        )
        text_request = components["TextProcessRequest"]["properties"]
        self.assertEqual(text_request["model"]["anyOf"][0]["enum"], ["dorna-8b-q3_k_m"])
        self.assertEqual(
            text_request["models"]["anyOf"][0]["items"]["enum"], ["dorna-8b-q3_k_m"]
        )


if __name__ == "__main__":
    unittest.main()
