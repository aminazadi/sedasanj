import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from asr_service.services import gpu_memory, inference
from asr_service.services.decision_processing import DecisionRuntimeRegistry
from asr_service.services.embedding_processing import EmbeddingRegistry
from asr_service.services.text_processing import GlobalModelPool


class ModelLifecycleTests(unittest.TestCase):
    def test_embedding_model_cannot_be_evicted_while_leased(self):
        registry = EmbeddingRegistry()
        with patch.object(registry, "get", return_value=(object(), object())):
            with registry.lease("embedding-model"):
                with self.assertRaises(HTTPException) as failure:
                    registry.evict("embedding-model")
                self.assertEqual(409, failure.exception.status_code)
        registry.evict("embedding-model")

    def test_gguf_idle_context_is_closed_when_model_is_removed(self):
        class Context:
            closed = False

            def close(self):
                self.closed = True

        pool = GlobalModelPool(1)
        context = Context()
        pool.idle[("old-model", 0, False)].append(context)
        pool.total = 1
        pool.evict("old-model")
        self.assertTrue(context.closed)
        self.assertEqual(0, pool.total)

    def test_evict_idle_embedding_skips_leased_and_other_devices(self):
        registry = EmbeddingRegistry()
        registry._models[("idle", 0)] = (object(), object())
        registry._models[("busy", 0)] = (object(), object())
        registry._models[("other", 1)] = (object(), object())
        registry._active["busy"] = 1
        self.assertEqual(1, registry.evict_idle(0))
        self.assertEqual({("busy", 0), ("other", 1)}, set(registry._models))
        self.assertEqual(0, registry.evict_idle(None))

    def test_evict_idle_decision_skips_leased(self):
        registry = DecisionRuntimeRegistry()
        registry._items[("idle", 0)] = {"model": object(), "active": 0}
        registry._items[("busy", 0)] = {"model": object(), "active": 1}
        self.assertEqual(1, registry.evict_idle(0))
        self.assertEqual([("busy", 0)], list(registry._items))

    def test_gguf_evict_device_closes_only_idle_contexts_on_that_gpu(self):
        pool = GlobalModelPool(2)
        first, second = Mock(), Mock()
        pool.idle[("a", 0, False)].append(first)
        pool.idle[("a", 1, False)].append(second)
        pool.total = 2
        self.assertEqual(1, pool.evict_device(0))
        first.close.assert_called_once()
        second.close.assert_not_called()
        self.assertEqual(1, pool.total)

    def test_asr_evict_removes_only_the_target_model(self):
        inference._clear_models()
        with patch.object(inference, "_build", side_effect=lambda mid, dev: object()):
            keep = inference._load("keep", None)
            inference._load("drop", None)
            inference.evict_model("drop")
            self.assertIs(keep, inference._load("keep", None))
            self.assertNotIn(("drop", None), inference._models)
        inference._clear_models()

    def test_asr_concurrent_load_builds_the_model_once(self):
        inference._clear_models()
        calls = []

        def slow_build(mid, device):
            calls.append(mid)
            time.sleep(0.05)
            return object()

        with patch.object(inference, "_build", side_effect=slow_build):
            results = []
            threads = [threading.Thread(target=lambda: results.append(inference._load("m", 0))) for _ in range(5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(1, len(calls))
        self.assertEqual(1, len({id(item) for item in results}))
        inference._clear_models()

    def test_asr_cache_keeps_four_most_recent_models(self):
        inference._clear_models()
        with patch.object(inference, "_build", side_effect=lambda mid, dev: object()):
            for index in range(5):
                inference._load(f"m{index}", None)
        self.assertEqual(4, len(inference._models))
        self.assertNotIn(("m0", None), inference._models)
        inference._clear_models()


class GpuMemoryTests(unittest.TestCase):
    def setUp(self):
        gpu_memory._active_jobs = 0
        gpu_memory._trim_pending = False
        gpu_memory._evictors.clear()

    def test_trim_waits_for_idle_window_and_never_runs_while_a_job_is_active(self):
        with patch.object(gpu_memory, "trim_now") as trim, patch.object(gpu_memory, "idle_trim_seconds", return_value=10), patch.object(gpu_memory, "_ensure_thread"):
            gpu_memory.job_started()
            gpu_memory.job_finished()
            now = gpu_memory._last_activity
            self.assertFalse(gpu_memory.trim_when_idle_due(now + 5))
            gpu_memory.job_started()
            self.assertFalse(gpu_memory.trim_when_idle_due(now + 60))
            trim.assert_not_called()
            gpu_memory._active_jobs = 0
            self.assertTrue(gpu_memory.trim_when_idle_due(now + 60))
            self.assertFalse(gpu_memory.trim_when_idle_due(now + 120))
            trim.assert_called_once()

    def test_trim_now_empties_torch_cache_only_when_torch_is_loaded(self):
        torch = Mock()
        torch.cuda.is_available.return_value = True
        with patch.dict(sys.modules, {"torch": torch}):
            gpu_memory.trim_now()
        torch.cuda.empty_cache.assert_called_once()
        with patch.dict(sys.modules, {"torch": None}):
            gpu_memory.trim_now()  # must not import or fail

    def test_evict_idle_calls_every_evictor_and_survives_failures(self):
        gpu_memory.register_idle_evictor("bad", Mock(side_effect=RuntimeError("x")))
        gpu_memory.register_idle_evictor("ok", Mock(return_value=2))
        with patch.object(gpu_memory, "trim_now") as trim:
            self.assertEqual(2, gpu_memory.evict_idle(0))
        trim.assert_called_once()

    def test_manager_can_be_switched_off(self):
        gpu_memory.register_idle_evictor("ok", Mock(return_value=1))
        with patch.dict("os.environ", {"ASR_GPU_MEMORY_MANAGER": "0"}):
            self.assertEqual(0, gpu_memory.evict_idle(0))


if __name__ == "__main__":
    unittest.main()
