import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from asr_service.web.dashboard import render_admin_page
from asr_service.web.resource_gauges import SCRIPT


@unittest.skipUnless(shutil.which("node"), "Node.js is required for dashboard JavaScript checks")
class ResourceGaugeTests(unittest.TestCase):
    def test_all_rendered_admin_scripts_parse(self):
        with tempfile.TemporaryDirectory() as directory:
            for view in ("dashboard", "models", "usage", "security", "keys", "settings"):
                page = render_admin_page(view)
                scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", page, re.S)
                script = Path(directory) / f"{view}.js"
                script.write_text("\n".join(scripts))
                result = subprocess.run(
                    ["node", "--check", str(script)], capture_output=True, text=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_gauges_show_compute_independently_from_memory_and_handle_missing_values(self):
        bootstrap = """
const assert=require('node:assert/strict');
const fa=String,esc=v=>String(v).replaceAll('<','&lt;'),bytes=v=>String(v),gpuBytes=bytes;
const key='',document={addEventListener(){}},setInterval=()=>{};
"""
        assertions = """
let zero=resourceDial(0,'compute');
assert.ok(zero.includes('stroke-dasharray="0 100"'));
let full=resourceDial(100,'compute');
assert.ok(full.includes('stroke-dasharray="100 100"'));
assert.ok(resourceDial(150,'compute').includes('stroke-dasharray="100 100"'));
assert.ok(resourceDial(null,'missing').includes('—'));
assert.ok(!resourceDial(null,'missing').includes('<line class="dial-needle"'));
let gpu=gpuResourceCard({name:'<gpu>',index:1,memory_total:12000,memory_free:3000,utilization_percent:0,active:0});
assert.ok(gpu.includes('&lt;gpu>'));
assert.ok(gpu.includes('stroke-dasharray="0 100"'));
assert.ok(gpu.includes('stroke-dasharray="75 100"'));
assert.equal((gpu.match(/class="resource-dial"/g)||[]).length,2);
let network=networkResourceCard({receive_bytes_per_second:2048,send_bytes_per_second:1024,interface:'eth0'},'network');
assert.ok(network.includes('2048/s'));
assert.ok(network.includes('1024/s'));
assert.ok(network.includes('مقیاس خودکار'));
"""
        result = subprocess.run(
            ["node", "-e", bootstrap + SCRIPT + assertions], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_resource_refresh_is_independent_of_heavy_dashboard_requests(self):
        page = render_admin_page("dashboard")
        self.assertIn("Promise.resolve(null),loadActiveRequests()", page)
        self.assertIn("setInterval(refreshResourceGauges,1000)", page)
        self.assertIn("SS-SYS-0001", page)
        self.assertIn("networkResourceCard(n,", page)
        self.assertIn(".map(gpuResourceCard)", page)
        self.assertIn("CUDA Sherpa:", render_admin_page("settings"))
        self.assertNotIn("renderModels();renderModelAnalytics", page)
        models = render_admin_page("models")
        self.assertIn("تکمیل فایل‌های GPU", models)
        self.assertIn("m.gpu_artifacts_ready===false", models)
