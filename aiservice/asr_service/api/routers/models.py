"""Model catalog and installation-management endpoints."""

import hashlib
import json
import re
from pathlib import PurePosixPath
try:
    import requests
except ImportError:
    requests = None
from fastapi import APIRouter, Depends, HTTPException, Response

from asr_service.domain.catalog import BUILTIN_MODEL_IDS, CATALOG, load_custom_models
from asr_service.infrastructure.storage import MODEL_DIR, execute, now, state
from asr_service.infrastructure.ninerouter import cached_models
from asr_service.services.downloader import manager

from ..dependencies import authorize_admin
from ..openapi import documented_responses
from ..schemas.common import ErrorResponse
from ..schemas.responses import ModelResponse, ModelStateResponse
from ..schemas.requests import CustomTextModelRequest

router = APIRouter(prefix="/api/models", tags=["Model management"], dependencies=[Depends(authorize_admin)])


def known(model_id: str):
    """Validate and return a model identifier from the static catalog."""

    if model_id not in CATALOG:
        raise HTTPException(404, "Unknown model")
    return model_id


def _safe_hf_artifact(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and path.suffix.lower() in {
        ".json", ".safetensors", ".txt", ".model", ".vocab", ".merges"
    }


def _sha256_remote(url: str) -> tuple[int, str]:
    response = requests.get(url, timeout=(5, 30), stream=True)
    response.raise_for_status()
    digest = hashlib.sha256()
    size = 0
    for chunk in response.iter_content(1024 * 1024):
        if chunk:
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _resolve_hugging_face_artifacts(body: CustomTextModelRequest) -> list[dict]:
    if requests is None:
        raise HTTPException(503, "requests is required to resolve Hugging Face artifacts")
    base = f"https://huggingface.co/api/models/{body.hf_repository}"
    try:
        metadata_response = requests.get(f"{base}/revision/{body.revision}", timeout=(5, 20))
        metadata_response.raise_for_status()
        metadata = metadata_response.json()
        if metadata.get("private") or metadata.get("gated"):
            raise HTTPException(422, "Only public, non-gated Hugging Face models are allowed")
        if metadata.get("sha") != body.revision:
            raise HTTPException(422, "Hugging Face did not resolve the requested immutable revision")
        tree = requests.get(
            f"{base}/tree/{body.revision}?recursive=true&expand=true", timeout=(5, 30)
        )
        tree.raise_for_status()
        entries = tree.json()
    except HTTPException:
        raise
    except (requests.RequestException, ValueError) as error:
        raise HTTPException(422, f"Unable to resolve public Hugging Face revision: {error}") from error
    prefix = (body.hf_subfolder.strip("/") + "/") if body.hf_subfolder else ""
    files = []
    for entry in entries:
        name = entry.get("path", "")
        if entry.get("type") != "file" or not name.startswith(prefix) or not _safe_hf_artifact(name):
            continue
        lfs = entry.get("lfs") or {}
        digest = lfs.get("oid")
        size = lfs.get("size")
        url = f"https://huggingface.co/{body.hf_repository}/resolve/{body.revision}/{name}?download=true"
        if not digest or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            size, digest = _sha256_remote(url)
        files.append({
            "filename": name[len(prefix):], "download_url": url,
            "expected_size": size, "sha256": digest.lower(),
        })
    if not files:
        raise HTTPException(422, "The pinned Hugging Face revision has no supported checksum-addressable artifacts")
    return files


@router.get(
    "",
    response_model=list[ModelResponse],
    summary="List available models",
    description="Lists every supported ASR, language, VAD, and denoising model with its local installation state.",
    responses=documented_responses(),
)
def models():
    """Return the static model catalog enriched with live installation state."""

    local = [
        {
            **vars(model),
            "files": [vars(item) for item in model.files],
            **state(model.id),
            "available": (MODEL_DIR / model.id / ".complete").exists(),
            "custom": model.id not in BUILTIN_MODEL_IDS,
        }
        for model in CATALOG.values()
    ]
    remote = [{"id": item["id"], "kind": item["kind"], "display_name": item["id"], "description": f"9Router {item.get('owned_by', '')}", "repository_url": "", "architecture": "9router", "recommended": False, "files": [], "model_id": item["id"], "status": "installed", "available": True, "custom": False, "source": {"provider": "9router"}} for item in cached_models()]
    return local + remote


@router.post("", response_model=ModelResponse, status_code=201, summary="Add a custom model",
             description="Adds either a downloadable GGUF language model or a complete faster-whisper CTranslate2 ASR bundle to the persistent catalog.")
def add_model(body: CustomTextModelRequest):
    if body.id in CATALOG:
        raise HTTPException(409, "A model with this id already exists")
    _save_custom_model(body)
    model = CATALOG[body.id]
    return {**vars(model), "files": [vars(item) for item in model.files], **state(model.id), "available": False, "custom": True}


def _save_custom_model(body: CustomTextModelRequest, *, replace: bool = False):
    decoding = {"context_size": body.context_size} if body.context_size else {}
    source = {"repository": body.hf_repository, "subfolder": body.hf_subfolder} if body.source_type == "huggingface" else {}
    files = [
        {"filename": item.filename, "download_url": str(item.download_url), "expected_size": item.expected_size, "sha256": item.sha256}
        for item in body.files or []
    ] or ([{
        "filename": body.filename, "download_url": str(body.download_url), "expected_size": body.expected_size, "sha256": body.sha256
    }] if body.kind == "llm" else [])
    if body.kind in {"decision", "embedding"} and body.source_type == "huggingface":
        files = _resolve_hugging_face_artifacts(body)
    if not files:
        raise HTTPException(422, "No model artifacts were provided")
    primary = files[0]
    command = """INSERT INTO custom_models(model_id,kind,display_name,description,repository_url,architecture,filename,download_url,expected_size,size_is_estimate,sha256,revision,license,preparation,language,task,decoding_json,files_json,engine,source_type,source_json,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,0,?,?,?,NULL,'fa',?,?,?,?,?,?,?)""", (
        body.id, body.kind, body.display_name, body.description,
        str(body.repository_url or body.download_url or primary["download_url"]),
        "fasterWhisper" if body.kind == "asr" else body.engine if body.kind == "decision" else "transformers" if body.kind == "embedding" else "gguf",
        primary["filename"], primary["download_url"],
        primary.get("expected_size"), primary.get("sha256"), body.revision,
        body.license, "transcribe" if body.kind == "asr" else "decision" if body.kind == "decision" else "embedding" if body.kind == "embedding" else "text-generation", json.dumps(decoding),
        json.dumps([{
            "filename": item["filename"], "url": item["download_url"],
            "expected_size": item.get("expected_size"), "sha256": item.get("sha256"),
        } for item in files]), body.engine, body.source_type if body.kind in {"decision", "embedding"} else None, json.dumps(source), now(),
    )
    if replace:
        execute("DELETE FROM custom_models WHERE model_id=?", (body.id,))
    execute(*command)
    load_custom_models()


@router.put("/{mid}", response_model=ModelResponse, summary="Update a custom model",
            description="Updates a custom model definition. Installed or actively downloading artifacts must be removed before changing the model type or files.")
def update_model(mid: str, body: CustomTextModelRequest):
    if mid in BUILTIN_MODEL_IDS:
        raise HTTPException(403, "Built-in model definitions cannot be edited")
    if mid not in CATALOG:
        raise HTTPException(404, "Unknown model")
    if body.id != mid:
        raise HTTPException(400, "Model id cannot be changed")
    current = CATALOG[mid]
    if body.kind in {"decision", "embedding"}:
        requested_source = (body.source_type, body.hf_repository, body.revision, body.hf_subfolder) if body.source_type == "huggingface" else (
            "direct", tuple((item.filename, str(item.download_url), item.sha256) for item in body.files or [])
        )
        current_source = (current.source_type, current.source.get("repository"), current.revision, current.source.get("subfolder")) if current.source_type == "huggingface" else (
            "direct", tuple((item.filename, item.url, item.sha256) for item in current.files)
        )
        changed_artifacts = current.kind != body.kind or current.engine != body.engine or current_source != requested_source
    elif body.kind == "asr":
        changed_artifacts = current.kind != body.kind or [(item.filename, item.url) for item in current.files] != [
            (item.filename, str(item.download_url)) for item in body.files or []
        ]
    else:
        changed_artifacts = current.kind != body.kind or len(current.files) != 1 or (
            current.files[0].filename, current.files[0].url
        ) != (body.filename, str(body.download_url))
    if changed_artifacts and ((MODEL_DIR / mid / ".complete").exists() or state(mid)["status"] in {"queued", "downloading", "preparing", "converting", "validating", "paused"}):
        raise HTTPException(409, "Delete the installed or partial model files before changing its type or artifacts")
    _save_custom_model(body, replace=True)
    model = CATALOG[mid]
    return {**vars(model), "files": [vars(item) for item in model.files], **state(mid), "available": (MODEL_DIR / mid / ".complete").exists(), "custom": True}


@router.delete("/{mid}", status_code=204, summary="Delete a model and its downloaded files",
               description="Removes installed and partial files. Built-in models remain in the catalog for reinstall; custom models are removed from the catalog. Active installations and tasks must finish or be stopped first.")
def delete_model(mid: str):
    manager.delete(mid, custom=mid not in BUILTIN_MODEL_IDS)
    return Response(status_code=204)


INSTALL_RESPONSES = documented_responses(
    **{"404": {"model": ErrorResponse, "description": "The model identifier is not present in the catalog."}}
)


@router.post(
    "/{mid}/install",
    response_model=ModelStateResponse,
    summary="Install a model",
    description="Starts or reuses the background installation job for a catalog model. Model files are downloaded and validated atomically.",
    responses=INSTALL_RESPONSES,
)
def install(mid: str):
    """Start a model installation and return its current state."""

    return manager.install(known(mid))


@router.post(
    "/{mid}/resume",
    response_model=ModelStateResponse,
    summary="Resume a model installation",
    description="Resumes a paused or interrupted model download using the same resumable installation workflow.",
    responses=INSTALL_RESPONSES,
)
def resume(mid: str):
    """Resume a model installation and return its current state."""

    return manager.install(known(mid))


@router.post(
    "/{mid}/pause",
    response_model=ModelStateResponse,
    summary="Pause a model installation",
    description="Pauses a model only while its installation is queued or downloading. Already received partial files remain available for resume.",
    responses=documented_responses(
        **{
            "404": {"model": ErrorResponse, "description": "The model identifier is not present in the catalog."},
            "409": {"model": ErrorResponse, "description": "The model is not currently queued or downloading."},
        }
    ),
)
def pause(mid: str):
    """Pause an eligible model installation and return the resulting state."""

    mid = known(mid)
    if state(mid)["status"] not in {"queued", "downloading"}:
        raise HTTPException(409, "Only a queued or downloading installation can be paused")
    manager.pause(mid)
    return state(mid)


@router.get(
    "/{mid}/status",
    response_model=ModelStateResponse,
    summary="Get model installation status",
    description="Returns live progress, transfer speed, timestamps, and any installation error for one catalog model.",
    responses=INSTALL_RESPONSES,
)
def model_status(mid: str):
    """Return the current installation state for a known model."""

    return state(known(mid))
