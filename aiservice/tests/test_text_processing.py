import threading
import unittest
from unittest.mock import MagicMock, patch

from asr_service.services import text_processing


class ModelPoolTests(unittest.TestCase):
    def test_pool_leases_independent_models_up_to_its_capacity(self):
        pool = text_processing.ModelPool("fake", 2)
        first_ready = threading.Event()
        release = threading.Event()
        leased = []

        def use_pool():
            with pool.lease() as model:
                leased.append(model)
                first_ready.set()
                release.wait(1)

        with patch.object(text_processing, "_load", side_effect=["model-1", "model-2"]) as load:
            first = threading.Thread(target=use_pool)
            second = threading.Thread(target=use_pool)
            first.start()
            self.assertTrue(first_ready.wait(1))
            second.start()
            for _ in range(100):
                if len(leased) == 2:
                    break
                threading.Event().wait(0.01)
            release.set()
            first.join(1)
            second.join(1)

        self.assertEqual({"model-1", "model-2"}, set(leased))
        self.assertEqual(2, load.call_count)

    def test_global_pool_evicts_idle_context_before_loading_another_model(self):
        pool = text_processing.GlobalModelPool(1)
        first = MagicMock()
        second = MagicMock()
        with patch.object(text_processing, "_load", side_effect=[first, second]) as load:
            with pool.lease("first"):
                pass
            with pool.lease("second") as leased:
                self.assertIs(second, leased)

        first.close.assert_called_once()
        self.assertEqual(2, load.call_count)
        self.assertEqual(1, pool.total)
