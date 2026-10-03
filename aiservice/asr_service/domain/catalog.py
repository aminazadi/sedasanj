"""Static catalog of supported model artifacts and metadata."""

import json
from dataclasses import dataclass, field

HF = "https://huggingface.co/{repo}/resolve/{revision}/{name}?download=true"

@dataclass(frozen=True)
class ModelFile:
    filename: str; url: str; expected_size: int | None = None; size_is_estimate: bool = False; sha256: str | None = None

@dataclass(frozen=True)
class ModelSpec:
    id: str; kind: str; display_name: str; description: str; repository_url: str
    architecture: str | None = None; recommended: bool = False; files: tuple[ModelFile, ...] = field(default_factory=tuple)
    revision: str | None = None; license: str | None = None; preparation: str | None = None
    language: str | None = None; task: str | None = None; decoding: dict = field(default_factory=dict)
    engine: str | None = None; source_type: str | None = None; source: dict = field(default_factory=dict)
    segment_timestamps: bool | None = None

def hf(repo, names, revision="main"):
    entries = ((*entry, None) if len(entry) == 3 else entry for entry in names)
    return tuple(ModelFile(n, HF.format(repo=repo, revision=revision, name=n), size, estimate, sha256) for n, size, estimate, sha256 in entries)

PERSIAN_V4_REVISION = "b84fc89f5d8c6a08acbd0930c74010f8bb555253"
BUZZASR_REVISION = "66e0306869c07b5075e9cdfd7b98c23aa4ecc122"
PERSIAN_V4_FILES = [
    ("added_tokens.json",34648,False),("config.json",1202,False),("generation_config.json",3850,False),("merges.txt",493869,False),
    ("model-00001-of-00002.safetensors",4993448880,False,"0830076bf44532970d62932089396549d5c8c430655065517e92f1d4ce66c2fb"),
    ("model-00002-of-00002.safetensors",1180663192,False,"1e393d0f267d0c11166aeeb5fd2eb1b6aa17003f9112d7e031c3872ab3198715"),
    ("model.safetensors.index.json",111598,False),("normalizer.json",52666,False),("preprocessor_config.json",357,False),
    ("special_tokens_map.json",2186,False),("tokenizer_config.json",282873,False),("vocab.json",1036558,False),
]
BUZZASR_FILES = [
    ("added_tokens.json",34648,False),("config.json",1196,False),("generation_config.json",471,False),("merges.txt",1075693,False),
    ("model.safetensors",3091247456,False,"fd91267e6c21939fa28d7bc7f1b887b009dd2e3489a11c3ca6244942bb7e0752"),
    ("normalizer.json",52666,False),("preprocessor_config.json",357,False),("special_tokens_map.json",2186,False),
    ("tokenizer_config.json",282873,False),("vocab.json",1653037,False),
]

CATALOG = {m.id:m for m in (
 ModelSpec("silero-vad","vad","Silero VAD","تشخیص گفتار و حذف سکوت (اجباری برای Shenava)","https://github.com/k2-fsa/sherpa-onnx",files=(ModelFile("silero_vad.onnx","https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",643854),)),
 ModelSpec("gtcrn-denoiser","denoiser","GTCRN Denoiser","کاهش نویز اختیاری پیش از رونویسی","https://github.com/k2-fsa/sherpa-onnx",files=(ModelFile("gtcrn_simple.onnx","https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx",1700000,True),)),
 ModelSpec("sherpa-diarization-2speaker","diarization","Sherpa two-speaker diarization","تفکیک محلی دو گوینده برای صوت تک‌کاناله","https://github.com/k2-fsa/sherpa-onnx",files=(ModelFile("segmentation.tar.bz2","https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",None,True),ModelFile("speaker-embedding.onnx","https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",None,True)),preparation="diarization_bundle"),
 ModelSpec("shenava-koochik","asr","شنوا کوچیک v1","مدل دقیق فارسی 114M","https://huggingface.co/Reza2kn/Shenava-Koochik-v1.0-sherpa-onnx","nemoCtc",True,hf("Reza2kn/Shenava-Koochik-v1.0-sherpa-onnx",[("model.onnx",458819249,False),("tokens.txt",12236,False)]),segment_timestamps=False),
 ModelSpec("shenava-koochik-v1-5-rnnt","asr","شنوا کوچیک v1.5 RNNT","مدل سبک‌تر با معماری Transducer","https://huggingface.co/Reza2kn/Shenava-Koochik-v1.5-RNNT-sherpa-onnx","transducer",False,hf("Reza2kn/Shenava-Koochik-v1.5-RNNT-sherpa-onnx",[("encoder.int8.onnx",131000000,True),("decoder.int8.onnx",3960000,True),("joiner.int8.onnx",1410000,True),("tokens.txt",12236,False)]),segment_timestamps=False),
 ModelSpec("shenava-rizeh","asr","شنوا ریزه","تعادل سرعت، حافظه و دقت","https://huggingface.co/Reza2kn/Shenava-Rizeh-v1.0-sherpa-onnx","nemoCtc",False,hf("Reza2kn/Shenava-Rizeh-v1.0-sherpa-onnx",[("model.onnx",116700660,False),("tokens.txt",12236,False)]),segment_timestamps=False),
 ModelSpec("shenava-rizeh-pizeh","asr","شنوا ریزه‌پیزه","سریع برای سرور ضعیف","https://huggingface.co/Reza2kn/Shenava-Rizeh-Pizeh-v1.0-sherpa-onnx","nemoCtc",False,hf("Reza2kn/Shenava-Rizeh-Pizeh-v1.0-sherpa-onnx",[("model.onnx",33201018,False),("tokens.txt",12236,False)]),segment_timestamps=False),
 ModelSpec("whisper-large-v3","asr","Whisper Large v3","نسخه CTranslate2 چندزبانه","https://huggingface.co/Systran/faster-whisper-large-v3","fasterWhisper",False,hf("Systran/faster-whisper-large-v3",[(n,None,True) for n in ["config.json","model.bin","tokenizer.json","vocabulary.json","preprocessor_config.json"]]),language="fa",task="transcribe",segment_timestamps=True),
 ModelSpec("whisper-persian-v4","asr","Whisper Persian v4","مدل دقیق فارسی؛ تبدیل محلی و امن به CTranslate2 INT8","https://huggingface.co/nezamisafa/whisper-persian-v4","fasterWhisper",True,hf("nezamisafa/whisper-persian-v4",PERSIAN_V4_FILES,PERSIAN_V4_REVISION),PERSIAN_V4_REVISION,"apache-2.0","whisper_ct2_int8","fa","transcribe",segment_timestamps=True),
 ModelSpec("buzzasr-persian","asr","BuzzASR Persian","مدل تک‌زبانه فارسی با tokenizer اختصاصی؛ CTranslate2 INT8","https://huggingface.co/BuzzASR/persian","fasterWhisper",False,hf("BuzzASR/persian",BUZZASR_FILES,BUZZASR_REVISION),BUZZASR_REVISION,"mit","whisper_ct2_int8","fa","transcribe",{"repetition_penalty":1.2,"no_repeat_ngram_size":3},segment_timestamps=True),
 ModelSpec("dorna-8b-q4_k_m","llm","Dorna 8B Q4_K_M","نسخه پیشنهادی با کیفیت بهتر؛ حدود ۶GB RAM","https://huggingface.co/QuantFactory/Dorna-Llama3-8B-Instruct-GGUF","gguf",True,hf("QuantFactory/Dorna-Llama3-8B-Instruct-GGUF",[("Dorna-Llama3-8B-Instruct.Q4_K_M.gguf",4920734240,False)])),
 ModelSpec("dorna-8b-q3_k_m","llm","Dorna 8B Q3_K_M","مصرف حافظه کمتر با افت کیفیت محدود","https://huggingface.co/QuantFactory/Dorna-Llama3-8B-Instruct-GGUF","gguf",False,hf("QuantFactory/Dorna-Llama3-8B-Instruct-GGUF",[("Dorna-Llama3-8B-Instruct.Q3_K_M.gguf",4018917920,False)])),
 ModelSpec("dorna-8b-q2_k","llm","Dorna 8B Q2_K","کم‌حجم‌ترین نسخه با کیفیت پایین‌تر","https://huggingface.co/QuantFactory/Dorna-Llama3-8B-Instruct-GGUF","gguf",False,hf("QuantFactory/Dorna-Llama3-8B-Instruct-GGUF",[("Dorna-Llama3-8B-Instruct.Q2_K.gguf",3179131424,False)])),
)}

BUILTIN_MODEL_IDS = frozenset(CATALOG)


def load_custom_models():
    """Merge persistent administrator-defined models into the runtime catalog."""

    from asr_service.infrastructure.storage import rows

    loaded = {}
    for item in rows("SELECT * FROM custom_models ORDER BY created_at"):
        file_data = json.loads(item["files_json"] or "[]")
        files = tuple(
            ModelFile(
                file["filename"], file["url"], file.get("expected_size"),
                bool(file.get("size_is_estimate", False)), file.get("sha256"),
            )
            for file in file_data
        ) or (ModelFile(
            item["filename"], item["download_url"], item["expected_size"],
            bool(item["size_is_estimate"]), item["sha256"]
        ),)
        loaded[item["model_id"]] = ModelSpec(
            id=item["model_id"], kind=item["kind"], display_name=item["display_name"],
            description=item["description"], repository_url=item["repository_url"],
            architecture=item["architecture"], files=files,
            revision=item["revision"], license=item["license"],
            preparation=item["preparation"], language=item["language"], task=item["task"],
            decoding=json.loads(item["decoding_json"] or "{}"), engine=item.get("engine"),
            source_type=item.get("source_type"), source=json.loads(item.get("source_json") or "{}"),
        )
    CATALOG.update(loaded)
    for model_id in set(CATALOG) - BUILTIN_MODEL_IDS - set(loaded):
        del CATALOG[model_id]
