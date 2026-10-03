"""Offline preparation and validation workflows for downloaded models."""

import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


class ModelPreparationError(RuntimeError):
    pass


def _run(command, env=None):
    result = subprocess.run(command, text=True, capture_output=True, env=env)
    if result.returncode:
        detail = (result.stderr or result.stdout or "unknown converter error").strip()
        raise ModelPreparationError(detail[-4000:])


def _make_fast_tokenizer(source):
    script = """
import json,sys
from transformers import WhisperTokenizerFast
root=sys.argv[1]
tok=WhisperTokenizerFast.from_pretrained(root,local_files_only=True)
cfg=json.load(open(root+'/config.json'))
vocab=tok.get_vocab()
if len(tok)>cfg['vocab_size'] or max(vocab.values())>=cfg['vocab_size']:
 raise RuntimeError(f\"tokenizer exceeds model vocabulary: {len(tok)} > {cfg['vocab_size']}\")
for key in ('decoder_start_token_id','eos_token_id','bos_token_id'):
 if not 0<=cfg[key]<cfg['vocab_size']:
  raise RuntimeError(f\"invalid {key}: {cfg[key]}\")
tok.save_pretrained(root)
"""
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    _run([sys.executable, "-c", script, str(source)], env)
    if not (source / "tokenizer.json").is_file():
        raise ModelPreparationError("transformers did not produce tokenizer.json")


def _validate_ctranslate2(output):
    required = ("model.bin", "config.json", "tokenizer.json", "preprocessor_config.json")
    missing = [name for name in required if not (output / name).is_file()]
    if missing:
        raise ModelPreparationError("converted model is missing: " + ", ".join(missing))
    script = """
import sys
from faster_whisper import WhisperModel
model=WhisperModel(sys.argv[1],device='cpu',compute_type='int8',cpu_threads=1)
del model
"""
    _run([sys.executable, "-c", script, str(output)])


def prepare_model(spec, staging, status_callback=lambda status: None):
    if spec.preparation == "diarization_bundle":
        staging = Path(staging)
        archive = staging / "segmentation.tar.bz2"
        status_callback("preparing")
        with tarfile.open(archive, "r:bz2") as package:
            members = [member for member in package.getmembers() if member.isfile()]
            model = next((member for member in members if member.name.endswith("/model.onnx")), None)
            if model is None or ".." in Path(model.name).parts:
                raise ModelPreparationError("diarization archive has no safe model.onnx")
            source = package.extractfile(model)
            if source is None:
                raise ModelPreparationError("unable to extract diarization model")
            (staging / "model.onnx").write_bytes(source.read())
        archive.unlink()
        return
    if spec.preparation != "whisper_ct2_int8":
        return
    staging = Path(staging)
    output = staging / ".converted"
    shutil.rmtree(output, ignore_errors=True)
    status_callback("preparing")
    _make_fast_tokenizer(staging)
    status_callback("converting")
    offline_env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    _run([
        "ct2-transformers-converter",
        "--model", str(staging),
        "--output_dir", str(output),
        "--quantization", "int8",
        "--copy_files", "tokenizer.json", "preprocessor_config.json",
    ], offline_env)
    shutil.copy2(staging / "generation_config.json", output / "generation_config.json")
    (output / "install_metadata.json").write_text(json.dumps({
        "source_repository": spec.repository_url,
        "source_revision": spec.revision,
        "license": spec.license,
        "backend": "faster-whisper",
        "quantization": "int8",
        "language": spec.language,
        "task": spec.task,
        "decoding": spec.decoding,
    }, ensure_ascii=False, indent=2))
    status_callback("validating")
    _validate_ctranslate2(output)
    for child in list(staging.iterdir()):
        if child == output:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in list(output.iterdir()):
        os.replace(child, staging / child.name)
    output.rmdir()
