import unittest
from unittest.mock import patch

from fastapi import HTTPException

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


if __name__ == "__main__":
    unittest.main()
