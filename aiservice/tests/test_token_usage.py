import tempfile
import unittest
from pathlib import Path

from asr_service.infrastructure import storage
from asr_service.services.token_usage import normalize_usage


class NormalizeUsageTests(unittest.TestCase):
    def test_reported_counts_are_kept_exactly(self):
        usage = normalize_usage({"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}, "local")
        self.assertEqual((12, 5, 17, "reported", "local"), tuple(usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens", "source", "origin")))

    def test_input_output_spelling_and_derived_total(self):
        usage = normalize_usage({"input_tokens": 7, "output_tokens": 3}, "9router")
        self.assertEqual((7, 3, 10, "reported"), (usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"], usage["source"]))

    def test_missing_or_partial_usage_is_unavailable_not_zero(self):
        for raw in (None, {}, {"prompt_tokens": 4}, {"prompt_tokens": "4", "completion_tokens": 1}, {"prompt_tokens": -1, "completion_tokens": 2}):
            usage = normalize_usage(raw, "local")
            self.assertEqual("unavailable", usage["source"], raw)
            self.assertIsNone(usage["total_tokens"] if raw in (None, {}) else None)


class TaskUsagePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        storage.DATA_DIR = root
        storage.MODEL_DIR = root / "models"
        storage.DB_PATH = root / "asr.sqlite3"
        storage.init_db()
        from asr_service.services import task_queue

        self.queue = task_queue

    def tearDown(self):
        self.temp.cleanup()

    def test_chat_usage_is_stored_on_run_history_and_public_task(self):
        task, _ = self.queue.enqueue("chat", "local", input_data={"messages": [], "options": {}})
        self.queue.chat_completion = lambda *_a, **_k: {
            "choices": [{"message": {"content": "سلام"}}],
            "usage": {"prompt_tokens": 21, "completion_tokens": 8, "total_tokens": 29},
        }
        manager = self.queue.TaskManager()
        manager._run(manager._claim("worker"), admitted_slot=object())
        public = self.queue.public_task(self.queue.get_task(task["task_id"]), False)
        self.assertEqual(
            (21, 8, 29, "reported", "local", "local"),
            tuple(public["usage"][k] for k in ("prompt_tokens", "completion_tokens", "total_tokens", "source", "origin", "model")),
        )
        history = storage.row("SELECT * FROM usage WHERE id=?", (task["usage_id"],))
        self.assertEqual((21, 8, 29, "reported"), (history["prompt_tokens"], history["completion_tokens"], history["total_tokens"], history["usage_source"]))

    def test_chat_without_upstream_usage_is_marked_unavailable(self):
        task, _ = self.queue.enqueue("chat", "local", input_data={"messages": [], "options": {}})
        self.queue.chat_completion = lambda *_a, **_k: {"choices": [{"message": {"content": "x"}}]}
        manager = self.queue.TaskManager()
        manager._run(manager._claim("worker"), admitted_slot=object())
        usage = self.queue.public_task(self.queue.get_task(task["task_id"]), False)["usage"]
        self.assertEqual(("unavailable", None), (usage["source"], usage["prompt_tokens"]))


if __name__ == "__main__":
    unittest.main()
