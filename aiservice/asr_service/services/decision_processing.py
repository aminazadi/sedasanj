"""Local, non-generative decision-model runtimes."""

import json
import os
import threading
import time
from contextlib import contextmanager

from fastapi import HTTPException

from asr_service.domain.catalog import CATALOG
from asr_service.infrastructure.storage import MODEL_DIR
from .resources import DECISION_CPU_THREADS, DECISION_MAX_CONCURRENT


CAPABILITIES = {
    "gliner2_5_multi_decide": frozenset({"choice", "multi_label", "score"}),
    "laya_multilingual": frozenset({"choice", "score", "noul"}),
}


def _state(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class DecisionRuntimeRegistry:
    """Bounded resident runtime cache. Models are loaded only from installed files."""

    def __init__(self):
        self._items = {}
        self._lock = threading.Condition()

    def evict(self, model_id):
        with self._lock:
            self._items.pop(model_id, None)

    def _load(self, model_id):
        spec = CATALOG.get(model_id)
        if not spec or spec.kind != "decision" or not spec.engine:
            raise HTTPException(422, "The selected model is not a decision model")
        root = MODEL_DIR / model_id
        if not (root / ".complete").is_file():
            raise HTTPException(503, "The selected decision model is not installed")
        os.environ.setdefault("OMP_NUM_THREADS", str(DECISION_CPU_THREADS))
        os.environ.setdefault("LAYA_THREADS", str(DECISION_CPU_THREADS))
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            if spec.engine == "gliner2_5_multi_decide":
                from gliner2 import GLiNER2
                return GLiNER2.from_pretrained(str(root))
            if spec.engine == "laya_multilingual":
                import laya
                return laya.load(str(root), device="cpu")
        except ImportError as error:
            raise HTTPException(503, f"Decision runtime dependency is unavailable: {error.name}") from error
        except Exception as error:
            raise HTTPException(503, f"Decision model failed to load: {error}") from error
        raise HTTPException(422, "Unsupported decision engine")

    @contextmanager
    def lease(self, model_id):
        with self._lock:
            item = self._items.get(model_id)
            if item is None:
                item = {"model": self._load(model_id), "active": 0}
                self._items[model_id] = item
            while item["active"] >= DECISION_MAX_CONCURRENT:
                self._lock.wait()
            item["active"] += 1
        try:
            yield item["model"]
        finally:
            with self._lock:
                item["active"] -= 1
                self._lock.notify_all()


registry = DecisionRuntimeRegistry()


def _question_payload(questions):
    return {
        key: {"type": value["type"], "instructions": value["instructions"], "criteria": value.get("criteria")}
        for key, value in questions.items()
    }


def _normalize(answer, question, threshold):
    if not isinstance(answer, dict):
        return {
            "type": question["type"], "answer": None, "probabilities": {},
            "confidence": 0.0, "margin": 0.0, "abstained": True,
        }
    probabilities = answer.get("probabilities") or answer.get("distribution") or {}
    value = answer.get("answer", answer.get("label"))
    if value is None:
        value = answer.get("choice", answer.get("score", answer.get("noul")))
    confidence_value = answer.get("confidence")
    if not probabilities and value is not None and confidence_value is not None:
        probabilities = {str(value): float(confidence_value)}
    ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    confidence = float(confidence_value if confidence_value is not None else ranked[0][1] if ranked else 0)
    margin = float(ranked[0][1] - ranked[1][1]) if len(ranked) > 1 else confidence
    abstained = confidence < threshold
    return {
        "type": question["type"], "answer": None if abstained else value,
        "probabilities": probabilities, "confidence": confidence, "margin": margin,
        "abstained": abstained,
    }


def decide(model_id, state, questions, threshold=0.72):
    spec = CATALOG.get(model_id)
    if not spec or spec.kind != "decision":
        raise HTTPException(422, "The selected model is not a decision model")
    unsupported = {item["type"] for item in questions.values()} - CAPABILITIES.get(spec.engine, frozenset())
    if unsupported:
        raise HTTPException(422, f"{spec.engine} does not support: {', '.join(sorted(unsupported))}")
    started = time.monotonic()
    payload = _question_payload(questions)
    with registry.lease(model_id) as model:
        if spec.engine == "laya_multilingual":
            raw = model.predict(state, payload)
            raw = raw.get("answers", raw) if isinstance(raw, dict) else {}
        else:
            text = _state(state)
            raw = {}
            for key, question in payload.items():
                criteria = question.get("criteria") or []
                labels = list(criteria) if isinstance(criteria, dict) else criteria
                schema = {key: {"labels": labels, "multi_label": question["type"] == "multi_label"}}
                result = model.classify_text(text, schema, include_confidence=True)
                raw[key] = result.get(key, result) if isinstance(result, dict) else result
    answers = {key: _normalize(raw.get(key, {}), question, threshold) for key, question in payload.items()}
    return {
        "version": "v1", "model": model_id, "engine": spec.engine, "answers": answers,
        "capabilities": sorted(CAPABILITIES[spec.engine]), "latency_ms": round((time.monotonic() - started) * 1000, 2),
    }
