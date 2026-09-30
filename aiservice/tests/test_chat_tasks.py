"""Contract and durable lifecycle checks for opt-in async chat inference."""

import json
import os
import tempfile
import unittest
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from asr_service.api.application import create_app
from asr_service.api.routers import openai_compat
from asr_service.api.dependencies import hash_key
from asr_service.domain.catalog import CATALOG
from asr_service.infrastructure import storage
from asr_service.services import task_queue


class AsyncChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model = next(k for k, v in CATALOG.items() if v.kind == "llm")
        self.patches = [patch.object(storage, "DATA_DIR", self.root),
                        patch.object(storage, "DB_PATH", self.root / "test.sqlite3"),
                        patch.object(storage, "MODEL_DIR", self.root / "models"),
                        patch.object(openai_compat, "MODEL_DIR", self.root / "models"),
                        patch.object(task_queue, "TASK_DIR", self.root / "tasks"),
                        patch.dict(os.environ, {"ASR_API_KEY": "master-test-secret"})]
        for item in self.patches:
            item.start()
        storage.init_db()
        folder = storage.MODEL_DIR / self.model
        folder.mkdir(parents=True)
        (folder / ".complete").touch()
        self.client = TestClient(create_app())
        self.headers = {"Authorization": "Bearer master-test-secret", "Idempotency-Key": "chat-key"}
        self.body = {"model": self.model, "messages": [
            {"role": "system", "content": "پاسخ را فقط به‌صورت JSON فارسی بازگردان"},
            {"role": "user", "content": "تماس آزمایشی"}], "temperature": 0.2, "max_tokens": 32}

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_submit_poll_result_idempotency_and_conflict(self):
        response = self.client.post("/v1/chat/tasks", headers=self.headers, json=self.body)
        self.assertEqual(response.status_code, 202, response.text)
        task = response.json()
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["result_url"], task["status_url"] + "/result")
        self.assertEqual(self.client.get(task["status_url"], headers=self.headers).json()["status"], "queued")
        pending = self.client.get(task["result_url"], headers=self.headers)
        self.assertEqual(pending.status_code, 409)
        self.assertEqual(pending.json()["error"]["code"], "result_not_ready")
        unauthenticated = self.client.get(task["status_url"])
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(unauthenticated.json()["error"]["code"], "authentication_failed")
        duplicate = self.client.post("/v1/chat/tasks", headers=self.headers, json=self.body)
        self.assertEqual(duplicate.json()["task_id"], task["task_id"])
        self.assertEqual(storage.row("SELECT count(*) n FROM tasks")["n"], 1)
        changed = self.client.post("/v1/chat/tasks", headers=self.headers, json={**self.body, "max_tokens": 33})
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json()["error"]["code"], "idempotency_conflict")
        self.assertNotIn("تماس آزمایشی", json.dumps(changed.json(), ensure_ascii=False))
        content = '{"خلاصه":"خوب"}'
        payload = {"id": "chatcmpl-fixed", "object": "chat.completion", "model": self.model,
                   "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}
        claimed = task_queue.TaskManager()._claim("test-worker")
        process = unittest.mock.MagicMock()
        process.communicate.return_value = (json.dumps(payload, ensure_ascii=False), "")
        process.returncode = 0
        process.__enter__.return_value = process
        with patch.object(task_queue.subprocess, "Popen", return_value=process):
            task_queue.TaskManager()._run(claimed)
        completed = self.client.get(task["status_url"], headers=self.headers)
        self.assertEqual(completed.json()["status"], "succeeded")
        self.assertNotIn(content, json.dumps(completed.json(), ensure_ascii=False))
        result = self.client.get(task["result_url"], headers=self.headers).json()
        self.assertEqual(result["choices"], payload["choices"])
        self.assertEqual(result["id"], payload["id"])
        self.assertEqual(result["object"], "chat.completion")
        history = self.client.get(f"/api/usage/{claimed['usage_id']}", headers=self.headers)
        self.assertEqual(history.status_code, 200)
        self.assertIsNone(history.json()["result"])
        self.assertIsNone(history.json()["runs"][0]["result"])
        self.assertEqual(self.client.post("/v1/chat/tasks", headers=self.headers, json=self.body).json()["task_id"], task["task_id"])

    def test_ownership_cancel_restart_and_failure(self):
        storage.execute("INSERT INTO api_keys(name,key_prefix,key_hash,scopes_json,created_at) VALUES(?,?,?,?,?)",
                        ("a", "key-a", hash_key("secret-a"), '["chat"]', storage.now()))
        storage.execute("INSERT INTO api_keys(name,key_prefix,key_hash,scopes_json,created_at) VALUES(?,?,?,?,?)",
                        ("b", "key-b", hash_key("secret-b"), '["chat"]', storage.now()))
        owner = {"Authorization": "Bearer secret-a", "Idempotency-Key": "shared"}
        other = {"Authorization": "Bearer secret-b", "Idempotency-Key": "shared"}
        task = self.client.post("/v1/chat/tasks", headers=owner, json=self.body).json()
        self.assertEqual(self.client.get(task["status_url"], headers=other).status_code, 404)
        self.assertEqual(self.client.get(task["result_url"], headers=self.headers).status_code, 404)
        self.assertEqual(self.client.delete(task["status_url"], headers=other).status_code, 404)
        distinct = self.client.post("/v1/chat/tasks", headers=other, json=self.body).json()
        self.assertNotEqual(task["task_id"], distinct["task_id"])
        task_queue.TaskManager()._recover()
        self.assertEqual(self.client.post("/v1/chat/tasks", headers=owner, json=self.body).json()["task_id"], task["task_id"])
        self.assertEqual(self.client.delete(task["status_url"], headers=owner).json()["status"], "cancelled")
        self.assertEqual(self.client.get(task["result_url"], headers=owner).json()["error"]["code"], "task_cancelled")
        claimed = task_queue.TaskManager()._claim("worker")
        self.assertEqual(claimed["task_id"], distinct["task_id"])
        process = unittest.mock.MagicMock()
        process.communicate.return_value = ("", "")
        process.returncode = 1
        process.__enter__.return_value = process
        storage.execute("UPDATE task_runs SET max_attempts=1 WHERE task_id=?", (distinct["task_id"],))
        with patch.object(task_queue.subprocess, "Popen", return_value=process):
            task_queue.TaskManager()._run(claimed)
        failure = self.client.get(distinct["status_url"], headers=other).json()
        self.assertEqual(failure["status"], "failed")
        self.assertEqual(failure["error_code"], "model_failure")

    def test_restart_recovers_interrupted_running_task_without_new_id(self):
        task = self.client.post("/v1/chat/tasks", headers=self.headers, json=self.body).json()
        claimed = task_queue.TaskManager()._claim("dead-worker")
        self.assertEqual(claimed["task_id"], task["task_id"])
        task_queue.TaskManager()._recover()
        recovered = self.client.get(task["status_url"], headers=self.headers).json()
        self.assertEqual(recovered["status"], "queued")
        self.assertEqual(self.client.post("/v1/chat/tasks", headers=self.headers, json=self.body).json()["task_id"], task["task_id"])
        self.assertEqual(storage.row("SELECT count(*) n FROM tasks")["n"], 1)

    def test_timeout_queue_capacity_model_and_authorization_codes(self):
        invalid = self.client.post("/v1/chat/tasks", headers=self.headers,
                                   json={**self.body, "messages": [{"role": "user", "content": "secret", "name": "n"}], "max_tokens": 0})
        self.assertEqual(invalid.status_code, 400)
        self.assertNotIn("secret", invalid.text)
        missing = self.client.post("/v1/chat/tasks", headers=self.headers,
                                   json={**self.body, "model": "no-such-model"})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "model_unavailable")
        unauthorized = self.client.post("/v1/chat/tasks", json=self.body)
        self.assertEqual(unauthorized.json()["error"]["code"], "authentication_failed")
        with patch.object(task_queue, "QUEUE_LIMIT", 0):
            full = self.client.post("/v1/chat/tasks", headers=self.headers, json=self.body)
        self.assertEqual(full.status_code, 503)
        self.assertEqual(full.json()["error"]["code"], "queue_full")
        task = self.client.post("/v1/chat/tasks", headers=self.headers, json=self.body).json()
        claimed = task_queue.TaskManager()._claim("worker")
        storage.execute("UPDATE task_runs SET max_attempts=1 WHERE task_id=?", (task["task_id"],))
        process = unittest.mock.MagicMock()
        timed_out = [False]
        def communicate(*args, **kwargs):
            if not timed_out[0]:
                timed_out[0] = True
                raise subprocess.TimeoutExpired("chat", 1)
            return "", ""
        process.communicate.side_effect = communicate
        process.__enter__.return_value = process
        real_clock = time.monotonic
        with patch.object(task_queue.subprocess, "Popen", return_value=process), patch.object(task_queue, "CHAT_TASK_TIMEOUT_SECONDS", 121), patch.object(task_queue.time, "monotonic", side_effect=lambda: real_clock() + (122 if timed_out[0] else 0)):
            task_queue.TaskManager()._run(claimed)
        self.assertEqual(process.kill.call_count, 1)
        self.assertEqual(self.client.get(task["status_url"], headers=self.headers).json()["error_code"], "task_timeout", storage.row("SELECT error FROM task_runs WHERE task_id=?", (task["task_id"],)))
        self.assertEqual(self.client.get(task["result_url"], headers=self.headers).json()["error"]["code"], "task_timeout")

    def test_running_cancellation_kills_only_its_inference_child(self):
        task = self.client.post("/v1/chat/tasks", headers=self.headers, json=self.body).json()
        claimed = task_queue.TaskManager()._claim("worker")
        process = unittest.mock.MagicMock()
        process.__enter__.return_value = process
        calls = [0]
        def communicate(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 1:
                cancelled = self.client.delete(task["status_url"], headers=self.headers)
                self.assertEqual(cancelled.status_code, 202)
                raise subprocess.TimeoutExpired("chat", 1)
            return "", ""
        process.communicate.side_effect = communicate
        with patch.object(task_queue.subprocess, "Popen", return_value=process):
            task_queue.TaskManager()._run(claimed)
        process.kill.assert_called_once()
        self.assertEqual(self.client.get(task["status_url"], headers=self.headers).json()["status"], "cancelled")

    def test_retention_purges_expired_result_and_allows_new_key_use(self):
        task = self.client.post("/v1/chat/tasks", headers=self.headers, json=self.body).json()
        expired = (datetime.now(timezone.utc) - timedelta(hours=task_queue.RESULT_TTL_HOURS + 1)).isoformat()
        storage.execute("UPDATE tasks SET status='succeeded',finished_at=?,result_json=? WHERE task_id=?",
                        (expired, '{"choices":[]}', task["task_id"]))
        storage.execute("UPDATE task_runs SET status='succeeded',result_json=? WHERE task_id=?",
                        ('{"choices":[]}', task["task_id"]))
        task_queue.TaskManager()._expire_chat_tasks()
        self.assertEqual(self.client.get(task["status_url"], headers=self.headers).status_code, 404)
        self.assertIsNone(storage.row("SELECT result_json FROM task_runs WHERE usage_id=(SELECT id FROM usage LIMIT 1)")["result_json"])
        repeated = self.client.post("/v1/chat/tasks", headers=self.headers, json=self.body).json()
        self.assertNotEqual(repeated["task_id"], task["task_id"])


if __name__ == "__main__":
    unittest.main()
