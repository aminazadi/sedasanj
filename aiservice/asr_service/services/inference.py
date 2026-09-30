import io, os, threading
from functools import lru_cache
from asr_service.domain.catalog import CATALOG
from asr_service.infrastructure.storage import MODEL_DIR
from .resources import ASR_CPU_THREADS,INFERENCE_SLOTS
THREADS = ASR_CPU_THREADS
COMPUTE = os.getenv("ASR_COMPUTE_TYPE", "int8")
DEVICE = os.getenv("ASR_DEVICE", "cpu")


class NoSpeechDetectedError(RuntimeError):
 """Raised only after decoding the original recording without VAD also fails."""


def _enabled(name, default=False):
 value = os.getenv(name)
 if value is None:
  return default
 return value.strip().lower() in {"1", "true", "yes", "on"}


def _denoiser_enabled():
 """Denoising changes speech content, so it must be an explicit operator choice."""
 return _enabled("ASR_ENABLE_DENOISER") and (MODEL_DIR / "gtcrn-denoiser" / ".complete").exists()
def _float_env(name,default):
 try:return float(os.getenv(name,default))
 except (TypeError,ValueError):return float(default)
WHISPER_TEMPERATURE=min(1.0,max(0.0,_float_env("ASR_WHISPER_TEMPERATURE","0")))
_locks_guard=threading.Lock();_engine_locks={}
def _engine_lock(mid):
 with _locks_guard:return _engine_locks.setdefault(mid,threading.Lock())
def normalize(t):return " ".join(t.replace("ي","ی").replace("ك","ک").split())
def _whisper_audio(audio,sample_rate):
 import soundfile as sf
 # faster-whisper treats every non-ndarray value as a path/file object. Sherpa's
 # denoiser may return a list, which PyAV then tries (and fails) to call read() on.
 # A WAV buffer also preserves the denoiser's sample rate; raw ndarrays are always
 # assumed by faster-whisper to already be 16 kHz.
 buffer=io.BytesIO();sf.write(buffer,audio,sample_rate,format="WAV",subtype="FLOAT");buffer.seek(0);return buffer
@lru_cache(maxsize=1)
def denoiser():
 import sherpa_onnx
 p=MODEL_DIR/"gtcrn-denoiser"/"gtcrn_simple.onnx";cfg=sherpa_onnx.OfflineSpeechDenoiserConfig(model=sherpa_onnx.OfflineSpeechDenoiserModelConfig(gtcrn=sherpa_onnx.OfflineSpeechDenoiserGtcrnModelConfig(model=str(p)),debug=False,num_threads=1,provider="cpu"));return sherpa_onnx.OfflineSpeechDenoiser(cfg)
@lru_cache(maxsize=2)
def load(mid):
 spec=CATALOG[mid];root=MODEL_DIR/mid
 if spec.architecture=="fasterWhisper":
  from faster_whisper import WhisperModel
  return WhisperModel(str(root),device=DEVICE,compute_type=COMPUTE,cpu_threads=THREADS,num_workers=1)
 import sherpa_onnx
 if spec.architecture=="nemoCtc":return sherpa_onnx.OfflineRecognizer.from_nemo_ctc(model=str(root/"model.onnx"),tokens=str(root/"tokens.txt"),num_threads=THREADS)
 return sherpa_onnx.OfflineRecognizer.from_transducer(encoder=str(root/"encoder.int8.onnx"),decoder=str(root/"decoder.int8.onnx"),joiner=str(root/"joiner.int8.onnx"),tokens=str(root/"tokens.txt"),num_threads=THREADS,model_type="nemo_transducer")
def _decode_whisper(engine, source, options):
 """Materialize the lazy segment iterator while its input stream is still alive."""
 iterator, info = engine.transcribe(source, **options)
 segments = [
  {"id": index, "start": segment.start, "end": segment.end, "text": normalize(segment.text)}
  for index, segment in enumerate(iterator)
 ]
 return [segment for segment in segments if segment["text"]], info


def transcribe(path,mid,beam,vad,prompt,on_event=None):
 event=on_event or (lambda _message:None)
 path=str(path)
 if not os.path.isfile(path):raise FileNotFoundError(f"Audio input does not exist: {path}")
 spec=CATALOG[mid];event(f"Loading ASR model {mid}");engine=load(mid);event("ASR model is ready")
 import soundfile as sf
 if spec.architecture=="fasterWhisper":
  event("Decoding audio with faster-whisper")
  options={"language":spec.language or "fa","task":spec.task or "transcribe","beam_size":beam,"vad_filter":vad,"initial_prompt":prompt or None,"temperature":WHISPER_TEMPERATURE,**spec.decoding}
  # The original upload is authoritative. In particular, an installed denoiser
  # must never silently replace every user's recording.
  seg, info = _decode_whisper(engine, path, options)
  if not seg and vad:
   event("VAD found no speech; retrying the original audio without VAD")
   retry_options = {**options, "vad_filter": False}
   seg, info = _decode_whisper(engine, path, retry_options)
  if not seg and _denoiser_enabled():
   event("No speech found in original audio; retrying with optional denoising")
   audio, sr = sf.read(path, dtype="float32", always_2d=True)
   audio = audio.mean(axis=1)
   enhanced = denoiser()(audio, sr)
   seg, info = _decode_whisper(engine, _whisper_audio(enhanced.samples, enhanced.sample_rate), options)
   if not seg and vad:
    seg, info = _decode_whisper(engine, _whisper_audio(enhanced.samples, enhanced.sample_rate), {**options, "vad_filter": False})
  event(f"Decoded {len(seg)} segment(s)")
  if not seg:
   raise NoSpeechDetectedError("No speech segments were detected in the original audio, with or without VAD")
  return normalize(" ".join(x["text"] for x in seg)),seg,info.duration,getattr(info,"duration_after_vad",None)
 event("Reading audio for sherpa-onnx")
 audio,sr=sf.read(path,dtype="float32",always_2d=True);audio=audio.mean(axis=1)
 event("Decoding audio with sherpa-onnx")
 with _engine_lock(mid):
  stream=engine.create_stream();stream.accept_waveform(sr,audio);engine.decode_stream(stream);text=normalize(stream.result.text)
 d=len(audio)/sr;return text,[{"id":0,"start":0,"end":d,"text":text}],d,d
