"""Local OpenAI-compatible embedding inference for installed models."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from asr_service.domain.catalog import CATALOG
from asr_service.infrastructure.storage import MODEL_DIR


class EmbeddingRegistry:
    def __init__(self) -> None:
        self._models: dict[str, tuple[Any, Any]] = {}
        self._lock = threading.Lock()

    def evict(self, model_id: str) -> None:
        with self._lock:
            self._models.pop(model_id, None)

    def get(self, model_id: str) -> tuple[Any, Any]:
        spec = CATALOG.get(model_id)
        if spec is None or spec.kind != "embedding":
            raise HTTPException(422, "The selected model is not an embedding model")
        root = MODEL_DIR / model_id
        if not (root / ".complete").is_file():
            raise HTTPException(503, "The selected embedding model is not installed")
        with self._lock:
            cached = self._models.get(model_id)
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
            loaded = (tokenizer, model)
            self._models[model_id] = loaded
            return loaded


registry = EmbeddingRegistry()


def embed(model_id: str, values: list[str]) -> tuple[list[list[float]], int]:
    import torch
    from torch.nn import functional

    tokenizer, model = registry.get(model_id)
    spec = CATALOG[model_id]
    max_length = int(spec.decoding.get("context_size") or 512)
    encoded = tokenizer(
        values,
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    with torch.inference_mode():
        output = model(**encoded)
        mask = encoded["attention_mask"].unsqueeze(-1).to(output.last_hidden_state.dtype)
        pooled = (output.last_hidden_state * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
        normalized = functional.normalize(pooled, p=2, dim=1)
    token_count = int(encoded["attention_mask"].sum().item())
    return normalized.cpu().tolist(), token_count


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
