import json, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import patch

from asr_service.infrastructure import storage


class TaskQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        storage.DATA_DIR = root
        storage.MODEL_DIR = root / "models"
        storage.DB_PATH = root / "asr.sqlite3"
        storage.init_db()
        from asr_service.services import task_queue

        self.queue = task_queue
        task_queue.TASK_DIR = root / "tasks"
        task_queue.POLL_SECONDS = 0.01

    def tearDown(self):
        self.temp.cleanup()

    def test_idempotency_and_successful_lifecycle(self):
        self.queue.process_text = lambda model, text, operation, style, *_args: {"output": text}
        manager = self.queue.TaskManager()
        manager.start()
        try:
            first, created = self.queue.enqueue(
                "text",
                "fake",
                input_data={
                    "text": "سلام",
                    "operation": "correction",
                    "style": "formal",
                },
                idempotency_key="request-1",
            )
            second, duplicate = self.queue.enqueue(
                "text",
                "fake",
                input_data={
                    "text": "سلام",
                    "operation": "correction",
                    "style": "formal",
                },
                idempotency_key="request-1",
            )
            self.assertTrue(created)
            self.assertFalse(duplicate)
            self.assertEqual(first["task_id"], second["task_id"])
            for _ in range(200):
                task = self.queue.get_task(first["task_id"])
                if task["status"] == "succeeded":
                    break
                time.sleep(0.01)
            self.assertEqual("succeeded", task["status"])
            self.assertEqual("سلام", self.queue.public_task(task)["result"]["output"])
            usage = storage.row(
                "SELECT status,execution_log,result_json FROM usage WHERE id=?", (task["usage_id"],)
            )
            self.assertEqual("success", usage["status"])
            self.assertEqual("سلام", json.loads(usage["result_json"])["output"])
            messages = [
                event["message"] for event in json.loads(usage["execution_log"])
            ]
            self.assertTrue(any("queued" in message for message in messages))
            self.assertTrue(
                any("Completed successfully" in message for message in messages)
            )
        finally:
            manager.stop()

    def test_active_usage_page_contains_only_live_tasks_oldest_first(self):
        from asr_service.api.routers import analytics

        first, _ = self.queue.enqueue("text", "first", input_data={"text": "a"})
        second, _ = self.queue.enqueue("text", "second", input_data={"text": "b"})
        storage.execute(
            "INSERT INTO usage(created_at,model_id,status) VALUES(?,?,'success')",
            (storage.now(), "finished"),
        )
        page = analytics.usage(page=1, page_size=1, active=True)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["items"][0]["task_id"], first["task_id"])
        self.assertEqual(page["items"][0]["status"], "queued")
        page = analytics.usage(page=2, page_size=1, active=True)
        self.assertEqual(page["items"][0]["task_id"], second["task_id"])

    def test_history_filters_use_persisted_request_fields_and_all_models(self):
        from asr_service.api.routers import analytics

        text_task, _ = self.queue.enqueue(
            "text", "dorna", input_data={"text": "x", "operation": "minutes"},
            response_format="json", client_ip="203.0.113.10",
        )
        asr_task, _ = self.queue.enqueue(
            "asr", models=["shenava", "whisper"], input_data={}, response_format="vtt",
            client_ip="203.0.113.11",
        )
        text_page = analytics.usage(page=1, page_size=20, kind="text", operation="minutes")
        self.assertEqual([text_task["usage_id"]], [item["id"] for item in text_page["items"]])
        self.assertEqual("minutes", text_page["items"][0]["operation"])
        model_page = analytics.usage(page=1, page_size=20, model="whisper", response_format="vtt")
        self.assertEqual([asr_task["usage_id"]], [item["id"] for item in model_page["items"]])
        self.assertEqual("asr", model_page["items"][0]["kind"])
        options = analytics.usage_filters()
        self.assertIn("whisper", options["models"])
        self.assertIn("minutes", options["operations"])
        self.assertIn("203.0.113.10", options["client_ips"])

    def test_admin_history_indexes_cover_usage_relationships(self):
        indexes = {
            item["name"]
            for item in storage.rows(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        self.assertTrue(
            {
                "tasks_usage_idx",
                "tasks_status_usage_idx",
                "task_runs_usage_position_idx",
                "task_events_usage_id_idx",
                "request_failures_reason_id_idx",
                "request_failures_phase_id_idx",
                "request_failures_status_code_id_idx",
            }.issubset(indexes)
        )

    def test_llm_claims_are_parallel_but_globally_bounded(self):
        tasks = [
            self.queue.enqueue("chat", "fake", input_data={"messages": []})[0]
            for _ in range(self.queue.LLM_MAX_CONCURRENT + 1)
        ]
        manager = self.queue.TaskManager()
        claimed = [manager._claim(f"worker-{index}") for index in range(len(tasks))]
        self.assertEqual(self.queue.LLM_MAX_CONCURRENT, sum(item is not None for item in claimed))
        self.assertIsNone(claimed[-1])

    def test_asr_can_claim_a_shared_slot_while_llm_is_running(self):
        llm, _ = self.queue.enqueue("chat", "fake", input_data={"messages": []})
        asr, _ = self.queue.enqueue(
            "asr", "fake-asr", input_path="/tmp/audio.wav", input_data={}
        )

        manager = self.queue.TaskManager()
        self.assertEqual(llm["task_id"], manager._claim("llm-worker")["task_id"])
        claimed_asr = manager._claim("asr-worker")

        self.assertIsNotNone(claimed_asr)
        self.assertEqual(asr["task_id"], claimed_asr["task_id"])

    def test_installed_local_model_wins_over_same_remote_identifier(self):
        model_dir = storage.MODEL_DIR
        local = model_dir / "whisper-large-v3"
        local.mkdir(parents=True)
        (local / ".complete").touch()

        with (
            patch.object(self.queue, "MODEL_DIR", model_dir),
            patch.object(self.queue, "is_configured_model", return_value=True),
        ):
            self.assertFalse(self.queue.uses_ninerouter("asr", "whisper-large-v3"))
            self.assertTrue(self.queue.uses_ninerouter("asr", "openai/whisper-1"))

    def test_single_plain_text_transcription_keeps_its_content_type_in_history(self):
        self.queue.TASK_DIR.mkdir(parents=True, exist_ok=True)
        audio = self.queue.TASK_DIR / "sample.wav"
        audio.write_bytes(b"RIFF")
        self.queue.transcribe = lambda *args, **kwargs: ("سلام", [], 1.0, 0.8)
        task, _ = self.queue.enqueue(
            "asr",
            "fake-asr",
            input_path=str(audio),
            input_data={"beam_size": 2, "vad_filter": True},
            response_format="text",
        )
        manager = self.queue.TaskManager()
        claimed = manager._claim("worker")
        self.assertIsNotNone(claimed)
        manager._run(claimed)
        usage = storage.row(
            "SELECT status,result_json,content_type FROM usage WHERE id=?",
            (task["usage_id"],),
        )
        self.assertEqual("success", usage["status"])
        self.assertEqual("سلام", json.loads(usage["result_json"]))
        self.assertEqual("text/plain", usage["content_type"])

    def test_no_speech_result_fails_once_instead_of_retrying_as_success(self):
        self.queue.TASK_DIR.mkdir(parents=True, exist_ok=True)
        audio = self.queue.TASK_DIR / "silent.wav"
        audio.write_bytes(b"RIFF")

        def no_speech(*_args, **_kwargs):
            raise self.queue.NoSpeechDetectedError("No speech segments were detected")

        self.queue.transcribe = no_speech
        task, _ = self.queue.enqueue(
            "asr", "fake-asr", input_path=str(audio), input_data={"vad_filter": True}
        )
        manager = self.queue.TaskManager()
        claimed = manager._claim("worker")
        manager._run(claimed)
        run = self.queue.get_runs(task["task_id"])[0]
        self.assertEqual("failed", run["status"])
        self.assertEqual(1, run["attempts"])
        self.assertEqual("failed", self.queue.get_task(task["task_id"])["status"])

    def test_atomic_claim(self):
        task, _ = self.queue.enqueue(
            "text",
            "fake",
            input_data={"text": "x", "operation": "correction", "style": "formal"},
        )
        manager = self.queue.TaskManager()
        claimed = [manager._claim("a"), manager._claim("b")]
        self.assertEqual(1, sum(item is not None for item in claimed))
        self.assertEqual("running", self.queue.get_task(task["task_id"])["status"])

    def test_ready_task_is_not_blocked_by_an_older_retry_backoff(self):
        delayed, _ = self.queue.enqueue(
            "text", "fake", input_data={"text": "delayed", "operation": "correction", "style": "formal"}
        )
        ready, _ = self.queue.enqueue(
            "text", "fake", input_data={"text": "ready", "operation": "correction", "style": "formal"}
        )
        future = "2999-01-01T00:00:00+00:00"
        storage.execute(
            "UPDATE tasks SET status='retrying',available_at=? WHERE task_id=?", (future, delayed["task_id"])
        )
        storage.execute(
            "UPDATE task_runs SET status='retrying',available_at=? WHERE task_id=?", (future, delayed["task_id"])
        )

        claimed = self.queue.TaskManager()._claim("worker")

        self.assertEqual(ready["task_id"], claimed["task_id"])

    def test_recovery_closes_interrupted_direct_chat_usage(self):
        usage_id = storage.execute(
            "INSERT INTO usage(created_at,model_id,filename,status,response_format) VALUES(?,?,'chat.completions','processing','json')",
            (self.queue.now(), "fake"),
        )
        self.queue.TaskManager()._recover()
        usage = storage.row("SELECT status,error FROM usage WHERE id=?", (usage_id,))
        self.assertEqual("failed", usage["status"])
        self.assertIn("restarted", usage["error"])

    def test_cancel_all_active_marks_queued_and_running_tasks_terminal(self):
        running, _ = self.queue.enqueue(
            "text", "fake", input_data={"text": "q", "operation": "correction", "style": "formal"}
        )
        queued, _ = self.queue.enqueue(
            "text", "fake", input_data={"text": "r", "operation": "correction", "style": "formal"}
        )
        manager = self.queue.TaskManager()
        self.assertEqual(running["task_id"], manager._claim("worker")["task_id"])

        interrupted = self.queue.cancel_all_active()

        self.assertEqual({queued["task_id"], running["task_id"]}, {x["task_id"] for x in interrupted})
        for task in (queued, running):
            saved = self.queue.get_task(task["task_id"])
            self.assertEqual("cancelled", saved["status"])
            self.assertEqual(1, saved["cancel_requested"])
            self.assertEqual("failed", storage.row("SELECT status FROM usage WHERE id=?", (task["usage_id"],))["status"])

    def test_first_success_skips_remaining_failover_models(self):
        calls = []
        self.queue.process_text = lambda model, text, operation, style, *_args: (
            calls.append(model) or {"corrected_text": model, "uncertain_items": []}
        )
        task, _ = self.queue.enqueue(
            "text",
            models=["first", "second", "third"],
            input_data={"text": "سلام", "operation": "correction", "style": "formal"},
        )
        manager = self.queue.TaskManager()
        manager.start()
        try:
            for _ in range(300):
                current = self.queue.get_task(task["task_id"])
                if current["status"] in self.queue.TERMINAL:
                    break
                time.sleep(0.01)
            self.assertEqual("succeeded", current["status"])
            self.assertEqual(["first"], calls)
            runs = self.queue.get_runs(task["task_id"])
            self.assertEqual([0, 1, 2], [x["position"] for x in runs])
            self.assertEqual(
                ["succeeded", "skipped", "skipped"],
                [x["status"] for x in runs],
            )
            self.assertEqual(
                [None, "failover_not_needed", "failover_not_needed"],
                [x["error"] for x in runs],
            )
            result = self.queue.public_task(current)["result"]
            self.assertEqual(
                ["first", "second", "third"], [x["model"] for x in result["results"]]
            )
        finally:
            manager.stop()

    def test_failed_model_falls_back_and_stops_after_success(self):
        old_attempts = self.queue.MAX_ATTEMPTS
        self.queue.MAX_ATTEMPTS = 1
        calls = []

        def process(model, text, operation, style, *_args):
            calls.append(model)
            if model == "bad":
                raise RuntimeError("broken")
            return {"corrected_text": model, "uncertain_items": []}

        self.queue.process_text = process
        task, _ = self.queue.enqueue(
            "text",
            models=["bad", "good", "later"],
            input_data={"text": "x", "operation": "correction", "style": "formal"},
        )
        manager = self.queue.TaskManager()
        manager.start()
        try:
            for _ in range(300):
                current = self.queue.get_task(task["task_id"])
                if current["status"] in self.queue.TERMINAL:
                    break
                time.sleep(0.01)
            self.assertEqual("succeeded", current["status"])
            self.assertEqual(["bad", "good"], calls)
            self.assertEqual(
                ["failed", "succeeded", "skipped"],
                [x["status"] for x in self.queue.get_runs(task["task_id"])],
            )
            self.assertIsNone(current["error"])
            self.assertIsNotNone(self.queue.public_task(current)["result_url"])
        finally:
            manager.stop()
            self.queue.MAX_ATTEMPTS = old_attempts

    def test_all_failed_models_return_aggregated_failure(self):
        old_attempts = self.queue.MAX_ATTEMPTS
        self.queue.MAX_ATTEMPTS = 1

        def process(model, *_args, **_kwargs):
            raise RuntimeError(f"{model} failed")

        self.queue.process_text = process
        task, _ = self.queue.enqueue(
            "text",
            models=["first", "second"],
            input_data={"text": "x", "operation": "correction", "style": "formal"},
        )
        manager = self.queue.TaskManager()
        manager.start()
        try:
            for _ in range(300):
                current = self.queue.get_task(task["task_id"])
                if current["status"] in self.queue.TERMINAL:
                    break
                time.sleep(0.01)
            self.assertEqual("failed", current["status"])
            self.assertEqual(
                ["failed", "failed"],
                [run["status"] for run in self.queue.get_runs(task["task_id"])],
            )
            self.assertIn("first:", current["error"])
            self.assertIn("second:", current["error"])
        finally:
            manager.stop()
            self.queue.MAX_ATTEMPTS = old_attempts

    def test_idempotency_rejects_different_fingerprint(self):
        self.queue.enqueue(
            "text",
            models=["a"],
            input_data={"text": "x"},
            idempotency_key="same",
            request_fingerprint="one",
        )
        with self.assertRaises(self.queue.IdempotencyConflict):
            self.queue.enqueue(
                "text",
                models=["b"],
                input_data={"text": "x"},
                idempotency_key="same",
                request_fingerprint="two",
            )

    def test_idempotency_keys_are_isolated_between_customers(self):
        first, _ = self.queue.enqueue(
            "text",
            models=["a"],
            input_data={"text": "x"},
            idempotency_key="shared-client-value",
            request_fingerprint="one",
            api_key_id=10,
        )
        second, _ = self.queue.enqueue(
            "text",
            models=["a"],
            input_data={"text": "x"},
            idempotency_key="shared-client-value",
            request_fingerprint="one",
            api_key_id=20,
        )
        duplicate, created = self.queue.enqueue(
            "text",
            models=["a"],
            input_data={"text": "x"},
            idempotency_key="shared-client-value",
            request_fingerprint="one",
            api_key_id=10,
        )
        self.assertNotEqual(first["task_id"], second["task_id"])
        self.assertFalse(created)
        self.assertEqual(first["task_id"], duplicate["task_id"])

    def test_recovery_finalizes_crash_after_successful_failover_run(self):
        task, _ = self.queue.enqueue(
            "text",
            models=["one", "two"],
            input_data={"text": "x", "operation": "correction", "style": "formal"},
        )
        first = self.queue.get_runs(task["task_id"])[0]
        storage.execute(
            "UPDATE task_runs SET status='succeeded',result_json='{}' WHERE id=?",
            (first["id"],),
        )
        storage.execute(
            "UPDATE tasks SET status='running' WHERE task_id=?", (task["task_id"],)
        )
        self.queue.TaskManager()._recover()
        self.assertEqual("succeeded", self.queue.get_task(task["task_id"])["status"])
        self.assertEqual(
            ["succeeded", "skipped"],
            [x["status"] for x in self.queue.get_runs(task["task_id"])],
        )

    def test_retry_backoff_cannot_be_overtaken_by_later_model(self):
        task, _ = self.queue.enqueue(
            "text", models=["first", "second"], input_data={"text": "x"}
        )
        first = self.queue.get_runs(task["task_id"])[0]
        storage.execute(
            "UPDATE task_runs SET status='retrying',available_at='9999-12-31T00:00:00+00:00' WHERE id=?",
            (first["id"],),
        )
        storage.execute(
            "UPDATE tasks SET status='retrying',available_at=? WHERE task_id=?",
            (storage.now(), task["task_id"]),
        )
        self.assertIsNone(self.queue.TaskManager()._claim("worker"))
        self.assertEqual(
            ["retrying", "pending"],
            [x["status"] for x in self.queue.get_runs(task["task_id"])],
        )

    def test_init_db_backfills_legacy_task_as_one_run(self):
        stamp = storage.now()
        with storage.closing(storage.connect()) as db, db:
            db.execute("DROP TABLE task_run_events")
            db.execute("DROP TABLE task_events")
            db.execute("DROP TABLE task_runs")
            db.execute("DROP TABLE schema_migrations")
            usage_id = db.execute(
                "INSERT INTO usage(created_at,model_id,status) VALUES(?,?,'success')",
                (stamp, "legacy-model"),
            ).lastrowid
            db.execute(
                """INSERT INTO tasks(task_id,kind,status,created_at,available_at,updated_at,model_id,max_attempts,usage_id)
                   VALUES('legacy','text','succeeded',?,?,?,'legacy-model',2,?)""",
                (stamp, stamp, stamp, usage_id),
            )
        storage.init_db()
        runs = storage.rows(
            "SELECT position,model_id,status FROM task_runs WHERE task_id='legacy'"
        )
        self.assertEqual(
            [{"position": 0, "model_id": "legacy-model", "status": "succeeded"}],
            runs,
        )

    def test_queue_limit_is_atomic_under_concurrent_admission(self):
        old_limit = self.queue.QUEUE_LIMIT
        self.queue.QUEUE_LIMIT = 1
        barrier = threading.Barrier(3)
        accepted = []
        rejected = []

        def submit(index):
            barrier.wait()
            try:
                accepted.append(
                    self.queue.enqueue(
                        "text", models=[f"m{index}"], input_data={"text": "x"}
                    )[0]
                )
            except OverflowError:
                rejected.append(index)

        threads = [threading.Thread(target=submit, args=(i,)) for i in range(2)]
        try:
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join()
            self.assertEqual(1, len(accepted))
            self.assertEqual(1, len(rejected))
        finally:
            self.queue.QUEUE_LIMIT = old_limit

    def test_queue_rejects_audio_bytes_beyond_weighted_capacity(self):
        with patch.object(self.queue, "QUEUE_MAX_AUDIO_BYTES", 10):
            self.queue.enqueue(
                "asr", models=["first"], input_data={}, audio_bytes=6
            )
            with self.assertRaises(OverflowError):
                self.queue.enqueue(
                    "asr", models=["second"], input_data={}, audio_bytes=5
                )

    def test_queue_rejects_model_runs_beyond_weighted_capacity(self):
        with patch.object(self.queue, "QUEUE_MAX_MODEL_RUNS", 2):
            self.queue.enqueue("text", models=["one", "two"], input_data={})
            with self.assertRaises(OverflowError):
                self.queue.enqueue("text", models=["three"], input_data={})

    def test_history_runs_survive_task_ttl_deletion(self):
        task, _ = self.queue.enqueue(
            "text", models=["one", "two"], input_data={"text": "x"}
        )
        usage_id = task["usage_id"]
        storage.execute("DELETE FROM tasks WHERE task_id=?", (task["task_id"],))
        runs = storage.rows(
            "SELECT task_id,model_id FROM task_runs WHERE usage_id=? ORDER BY position",
            (usage_id,),
        )
        self.assertEqual(["one", "two"], [x["model_id"] for x in runs])
        self.assertTrue(all(x["task_id"] is None for x in runs))
        events = storage.rows(
            "SELECT task_id,message FROM task_events WHERE usage_id=?", (usage_id,)
        )
        self.assertTrue(events)
        self.assertTrue(all(x["task_id"] is None for x in events))


if __name__ == "__main__":
    unittest.main()
