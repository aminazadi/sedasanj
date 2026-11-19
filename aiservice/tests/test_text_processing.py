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


class ContextFallbackTests(unittest.TestCase):
    def _llama_module(self, side_effect):
        module = MagicMock()
        module.Llama = MagicMock(side_effect=side_effect)
        return module

    def test_context_failure_retries_with_half_context_then_succeeds(self):
        failure = ValueError("Failed to create llama_context")
        module = self._llama_module([failure, "model"])
        with patch.dict("sys.modules", {"llama_cpp": module}), patch.object(
            text_processing.gpu_runtime, "llm_context_size", return_value=12288
        ), patch.object(text_processing, "_build_options", side_effect=lambda mid, ctx, dev, split: {"n_ctx": ctx, "dev": dev}):
            self.assertEqual("model", text_processing._load("m", device_index=1))
        self.assertEqual([12288, 6144], [call.kwargs["n_ctx"] for call in module.Llama.call_args_list])

    def test_context_failure_falls_back_to_cpu_and_raises_typed_error_when_all_fail(self):
        failure = ValueError("Failed to create llama_context")
        module = self._llama_module([failure, failure, failure])
        with patch.dict("sys.modules", {"llama_cpp": module}), patch.object(
            text_processing.gpu_runtime, "llm_context_size", return_value=12288
        ), patch.object(text_processing, "_build_options", side_effect=lambda mid, ctx, dev, split: {"n_ctx": ctx, "dev": dev}):
            with self.assertRaises(text_processing.ModelContextError):
                text_processing._load("m", device_index=1)
        self.assertEqual([1, 1, None], [call.kwargs["dev"] for call in module.Llama.call_args_list])

    def test_non_resource_errors_are_not_retried(self):
        module = self._llama_module([ValueError("model file is corrupt")])
        with patch.dict("sys.modules", {"llama_cpp": module}), patch.object(
            text_processing.gpu_runtime, "llm_context_size", return_value=12288
        ), patch.object(text_processing, "_build_options", return_value={}):
            with self.assertRaises(ValueError):
                text_processing._load("m", device_index=1)
        self.assertEqual(1, module.Llama.call_count)

    def test_attempt_order_never_goes_below_minimum_context(self):
        self.assertEqual([(3000, None)], text_processing._load_attempts(3000, None))
        self.assertEqual([(4096, 0), (2048, 0), (4096, None)], text_processing._load_attempts(4096, 0))


class SegmentCorrectionTests(unittest.TestCase):
    def test_segment_prompt_uses_strict_schema_and_preserves_ids(self):
        segments = [
            {"id": "a", "channel": 0, "t_start_ms": 0, "t_end_ms": 1000, "text": "سلام"},
            {"id": "b", "channel": 1, "t_start_ms": 1100, "t_end_ms": 2000, "text": "درود"},
        ]
        messages, options = text_processing.process_messages(
            None, "correction", "formal", segments, "Correct conservatively"
        )
        self.assertEqual("json_schema", options["response_format"]["type"])
        self.assertIn('"id":"a"', messages[1]["content"])

        parsed = text_processing.process_response(
            '{"segments":[{"id":"a","corrected_text":"سلام.","uncertain":false},'
            '{"id":"b","corrected_text":"درود.","uncertain":false}],"uncertain_items":[]}',
            "correction",
            "formal",
            segments,
        )
        self.assertEqual("سلام.\nدرود.", parsed["corrected_text"])

    def test_segment_response_rejects_reordering(self):
        segments = [
            {"id": "a", "channel": 0, "t_start_ms": 0, "t_end_ms": 1000, "text": "سلام"},
            {"id": "b", "channel": 1, "t_start_ms": 1100, "t_end_ms": 2000, "text": "درود"},
        ]
        with self.assertRaises(ValueError):
            text_processing.process_response(
                '{"segments":[{"id":"b","corrected_text":"درود","uncertain":false},'
                '{"id":"a","corrected_text":"سلام","uncertain":false}],"uncertain_items":[]}',
                "correction",
                "formal",
                segments,
            )

    def test_segment_response_extracts_json_from_markdown(self):
        segments = [
            {"id": "a", "channel": 0, "t_start_ms": 0, "t_end_ms": 1000, "text": "سلام"},
        ]

        parsed = text_processing.process_response(
            'خروجی:\n```json\n{"segments":[{"id":"a","corrected_text":"سلام.",'
            '"uncertain":false}],"uncertain_items":[]}\n```',
            "correction",
            "formal",
            segments,
        )

        self.assertEqual(parsed["segments"][0]["corrected_text"], "سلام.")
        self.assertEqual(parsed["corrected_text"], "سلام.")

    def test_monolithic_correction_is_mapped_to_original_segments_as_uncertain(self):
        segments = [
            {"id": "a", "channel": 0, "t_start_ms": 0, "t_end_ms": 1000, "text": "سلام خوبی"},
            {"id": "b", "channel": 1, "t_start_ms": 1100, "t_end_ms": 2000, "text": "بله ممنون"},
        ]

        parsed = text_processing.process_response(
            "سلام، خوبی؟ بله، ممنون.",
            "correction",
            "formal",
            segments,
        )

        self.assertEqual([item["id"] for item in parsed["segments"]], ["a", "b"])
        self.assertTrue(all(item["uncertain"] for item in parsed["segments"]))
        self.assertEqual(len(parsed["uncertain_items"]), 2)
        self.assertEqual(parsed["normalized_from"], "plain_text")

    def test_corrected_text_only_object_is_mapped_to_original_segments(self):
        segments = [
            {"id": "a", "channel": 0, "t_start_ms": 0, "t_end_ms": 1000, "text": "سلام"},
            {"id": "b", "channel": 1, "t_start_ms": 1100, "t_end_ms": 2000, "text": "درود"},
        ]

        parsed = text_processing.process_response(
            '{"corrected_text":"سلام. درود.","uncertain_items":[]}',
            "correction",
            "formal",
            segments,
        )

        self.assertEqual([item["id"] for item in parsed["segments"]], ["a", "b"])
        self.assertTrue(all(item["uncertain"] for item in parsed["segments"]))


class LocalGrammarEnforcementTests(unittest.TestCase):
    """llama-cpp-python only turns response_format into a grammar for type
    "json_object"; a "json_schema" response_format must be converted into an
    explicit grammar for the local model, or segment correction decodes
    unconstrained and the strict schema is silently ignored."""

    def test_json_schema_response_format_is_converted_to_an_explicit_grammar(self):
        schema = {"type": "object", "properties": {"segments": {"type": "array"}}}
        options = {
            "max_tokens": 4096,
            "response_format": {"type": "json_schema", "json_schema": {"schema": schema}},
        }
        grammar_module = MagicMock()
        grammar_module.LlamaGrammar.from_json_schema = MagicMock(return_value="compiled-grammar")

        with patch.dict("sys.modules", {"llama_cpp": grammar_module}):
            result = text_processing._local_grammar_options(options)

        self.assertEqual("compiled-grammar", result["grammar"])
        grammar_module.LlamaGrammar.from_json_schema.assert_called_once()
        (called_schema_json,), _ = grammar_module.LlamaGrammar.from_json_schema.call_args
        self.assertEqual(schema, __import__("json").loads(called_schema_json))
        # The original options (minus the added grammar) are preserved untouched.
        self.assertEqual(options["max_tokens"], result["max_tokens"])

    def test_non_json_schema_response_formats_pass_through_unchanged(self):
        for options in (
            {"max_tokens": 10},
            {"max_tokens": 10, "response_format": {"type": "json_object"}},
        ):
            self.assertEqual(options, text_processing._local_grammar_options(options))

    def test_process_passes_the_compiled_grammar_to_the_local_model(self):
        segments = [{"id": "a", "channel": 0, "t_start_ms": 0, "t_end_ms": 1000, "text": "سلام"}]
        fake_model = MagicMock()
        fake_model.create_chat_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"segments":[{"id":"a","corrected_text":"سلام.","uncertain":false}],'
                        '"uncertain_items":[]}'
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 1},
        }
        grammar_module = MagicMock()
        grammar_module.LlamaGrammar.from_json_schema = MagicMock(return_value="compiled-grammar")

        with patch.dict("sys.modules", {"llama_cpp": grammar_module}), patch.object(
            text_processing, "_pool"
        ) as pool:
            pool.return_value.lease.return_value.__enter__.return_value = fake_model
            text_processing.process("m", None, "correction", "formal", segments, "Correct conservatively")

        self.assertEqual("compiled-grammar", fake_model.create_chat_completion.call_args.kwargs["grammar"])
