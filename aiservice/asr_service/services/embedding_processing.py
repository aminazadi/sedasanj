"""Local OpenAI-compatible embedding inference for installed models."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from asr_service.domain.catalog import CATALOG
from asr_service.infrastructure.storage import MODEL_DIR
from . import gpu_runtime


class EmbeddingRegistry:
    def __init__(self) -> None:
        self._models: dict[tuple[str, int | None], tuple[Any, Any]] = {}
        self._active: dict[str, int] = {}
        self._lock = threading.RLock()

    def evict(self, model_id: str) -> None:
        with self._lock:
            if self._active.get(model_id, 0):
                raise HTTPException(409, "Wait for active embedding inference before deleting this model")
            for key in [key for key in self._models if key[0] == model_id]:
                self._models.pop(key, None)

    @contextmanager
    def lease(self, model_id: str):
        with self._lock:
            loaded = self.get(model_id)
            self._active[model_id] = self._active.get(model_id, 0) + 1
        try:
            yield loaded
        finally:
            with self._lock:
                self._active[model_id] -= 1

    def get(self, model_id: str) -> tuple[Any, Any]:
        spec = CATALOG.get(model_id)
        if spec is None or spec.kind != "embedding":
            raise HTTPException(422, "The selected model is not an embedding model")
        root = MODEL_DIR / model_id
        if not (root / ".complete").is_file():
            raise HTTPException(503, "The selected embedding model is not installed")
        device_index = gpu_runtime.current_device_index()
        cache_key = (model_id, device_index)
        with self._lock:
            cached = self._models.get(cache_key)
            if cached is not None:
                return cached
            from transformers import AutoModel, AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(
                root,
                local_files_only=True,
                trust_remote_code=False,
            )
            model = AutoModel.from_pretrained(
                root,
                local_files_only=True,
                trust_remote_code=False,
            )
            model.eval()
            if device_index is not None:
                model = model.to(f"cuda:{device_index}")
            loaded = (tokenizer, model)
            self._models[cache_key] = loaded
            return loaded


registry = EmbeddingRegistry()


def embed(model_id: str, values: list[str]) -> tuple[list[list[float]], int]:
    import torch
    from torch.nn import functional

    with registry.lease(model_id) as (tokenizer, model):
        spec = CATALOG[model_id]
        max_length = int(spec.decoding.get("context_size") or 512)
        encoded = tokenizer(
            values,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        device = next(model.parameters()).device
        encoded = {key: tensor.to(device) for key, tensor in encoded.items()}
        with torch.inference_mode():
            output = model(**encoded)
            mask = encoded["attention_mask"].unsqueeze(-1).to(output.last_hidden_state.dtype)
            pooled = (output.last_hidden_state * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
            normalized = functional.normalize(pooled, p=2, dim=1)
        token_count = int(encoded["attention_mask"].sum().item())
        return normalized.cpu().tolist(), token_count


def embed_scheduled(model_id: str, values: list[str]) -> tuple[list[list[float]], int]:
    from .resources import admission_allowed, inference_slot

    if gpu_runtime.gpu_eligible("embedding", model_id):
        deadline = time.monotonic() + gpu_runtime.gpu_wait_seconds()
        while True:
            devices = sorted(gpu_runtime.enabled_devices(), key=lambda item: (item["utilization_percent"], -item["memory_free"]))
            for device in devices:
                try:
                    with gpu_runtime.reserve(device, timeout=0):
                        return embed(model_id, values)
                except TimeoutError:
                    continue
            if time.monotonic() >= deadline:
                break
            time.sleep(min(0.1, deadline - time.monotonic()))
        if gpu_runtime.get_settings()["mode"] == "gpu":
            raise HTTPException(503, "GPU capacity is currently unavailable")
    elif gpu_runtime.get_settings()["mode"] == "gpu" and gpu_runtime.cuda_model_family("embedding", model_id):
        raise HTTPException(503, "GPU runtime is currently unavailable")
    while not admission_allowed():
        time.sleep(0.25)
    with inference_slot():
        return embed(model_id, values)


def validate_embedding_bundle(folder: Path) -> None:
    names = {str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file()}
    if "config.json" not in names or not any(name.endswith(".safetensors") for name in names):
        raise ValueError("embedding bundle requires config.json and safetensors weights")
    tokenizer_artifacts = ("tokenizer.json", "vocab.txt", "sentencepiece.bpe.model")
    if not any(name in names for name in tokenizer_artifacts):
        raise ValueError("embedding bundle requires tokenizer artifacts")
    if any(name.endswith((".bin", ".pt", ".pkl", ".pickle")) for name in names):
        raise ValueError("unsafe embedding bundle artifact")
    for path in folder.rglob("*.json"):
        import json

        config = json.loads(path.read_text())
        if isinstance(config, dict) and (config.get("auto_map") or config.get("trust_remote_code")):
            raise ValueError("embedding bundles may not require remote code")
    script = (
        "from transformers import AutoModel,AutoTokenizer;"
        "import sys;"
        "AutoTokenizer.from_pretrained(sys.argv[1],local_files_only=True,trust_remote_code=False);"
        "AutoModel.from_pretrained(sys.argv[1],local_files_only=True,trust_remote_code=False)"
    )
    environment = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    result = subprocess.run(
        [sys.executable, "-c", script, str(folder)],
        check=False,
        text=True,
        capture_output=True,
        env=environment,
        timeout=120,
    )
    if result.returncode:
        raise ValueError("embedding smoke failed: " + (result.stderr or result.stdout)[-1000:])
