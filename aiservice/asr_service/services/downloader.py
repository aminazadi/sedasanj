import hashlib,json,os,shutil,subprocess,threading,time,uuid
try:
 import requests
except ImportError:  # Lightweight documentation/test environments do not download artifacts.
 requests = None
from fastapi import HTTPException
from asr_service.domain.catalog import CATALOG
from asr_service.infrastructure.proxy import download_session
from asr_service.infrastructure import storage
from asr_service.infrastructure.storage import MODEL_DIR,audit,now,set_state,state
from .model_builder import prepare_model
class Paused(Exception):pass
class DownloadManager:
 def __init__(self):self.stops={};self.threads={};self.lock=threading.Lock()
 def install(self,mid):
  with self.lock:
   if mid in self.threads and self.threads[mid].is_alive():return state(mid)
   job=str(uuid.uuid4());stop=threading.Event();self.stops[mid]=stop;set_state(mid,status="queued",error=None,job_id=job);t=threading.Thread(target=self._run,args=(mid,stop),daemon=True);self.threads[mid]=t;t.start();audit("install",mid,job);return state(mid)
 def pause(self,mid):
  if mid in self.stops:self.stops[mid].set()
  set_state(mid,status="paused",speed_bps=0);audit("pause",mid)
 def delete(self,mid,*,custom=False):
  """Remove only this model's files; keep built-in catalog entries available for reinstall."""
  with self.lock:
   if mid not in CATALOG:raise HTTPException(404,"Unknown model")
   if self.threads.get(mid) and self.threads[mid].is_alive():
    raise HTTPException(409,"Pause the installation and wait for it to stop before deleting")
   if storage.row("SELECT id FROM task_runs WHERE model_id=? AND status IN ('pending','retrying','processing') LIMIT 1",(mid,)):
    raise HTTPException(409,"Cancel or finish active tasks using this model before deleting")
   if storage.row("SELECT task_id FROM tasks WHERE model_id=? AND status IN ('queued','retrying','running') LIMIT 1",(mid,)):
    raise HTTPException(409,"Cancel or finish active tasks using this model before deleting")
   if CATALOG[mid].kind == "decision":
    from .decision_processing import registry
    registry.evict(mid)
   for folder in (MODEL_DIR/mid,MODEL_DIR/(mid+".staging")):
    if folder.is_symlink():raise HTTPException(409,"Model directory is a symbolic link")
    if folder.is_dir():shutil.rmtree(folder)
    elif folder.exists():folder.unlink()
   storage.execute("DELETE FROM model_state WHERE model_id=?",(mid,))
   if custom:
    from asr_service.domain.catalog import load_custom_models
    storage.execute("DELETE FROM custom_models WHERE model_id=?",(mid,))
    load_custom_models()
   audit("delete",mid,"custom" if custom else "builtin")
 def _run(self,mid,stop):
  spec=CATALOG[mid];folder=MODEL_DIR/(mid+".staging");folder.mkdir(parents=True,exist_ok=True);total=sum(f.expected_size or 0 for f in spec.files);received=sum((folder/(f.filename+".part")).stat().st_size if (folder/(f.filename+".part")).exists() else 0 for f in spec.files);set_state(mid,status="downloading",received_bytes=received,total_bytes=total,error=None)
  try:
   (folder/".complete").unlink(missing_ok=True);(folder/"manifest.json").unlink(missing_ok=True)
   if spec.preparation:
    present=sum((folder/f.filename).stat().st_size if (folder/f.filename).exists() else (folder/(f.filename+".part")).stat().st_size if (folder/(f.filename+".part")).exists() else 0 for f in spec.files)
    required=max(0,total-present)+3*1024**3;free=shutil.disk_usage(MODEL_DIR).free
    if free<required:raise RuntimeError(f"insufficient disk space: need {required} bytes free, have {free}")
   for f in spec.files:received=self._file(mid,f,folder,stop,received,total)
   set_state(mid,status="validating",speed_bps=0)
   for f in spec.files:
    p=folder/f.filename
    if not p.exists() or (f.expected_size and not f.size_is_estimate and p.stat().st_size!=f.expected_size):raise ValueError(f"invalid size: {f.filename}")
    h=hashlib.sha256()
    with p.open("rb") as src:
     while b:=src.read(4*1024*1024):h.update(b)
    if f.sha256 and h.hexdigest()!=f.sha256:raise ValueError(f"invalid checksum: {f.filename}")
   prepare_model(spec,folder,lambda status:set_state(mid,status=status,speed_bps=0))
   if spec.kind == "decision":
    set_state(mid,status="validating",speed_bps=0)
    self._validate_decision_bundle(spec, folder)
   manifest={"model":mid,"source_revision":spec.revision,"installed_at":now(),"files":[]}
   for p in sorted(x for x in folder.rglob("*") if x.is_file() and not x.name.endswith(".part")):
    h=hashlib.sha256()
    with p.open("rb") as src:
     while b:=src.read(4*1024*1024):h.update(b)
    manifest["files"].append({"name":str(p.relative_to(folder)),"bytes":p.stat().st_size,"sha256":h.hexdigest()})
   (folder/"manifest.json").write_text(json.dumps(manifest,indent=2));(folder/".complete").write_text(now());active=MODEL_DIR/mid
   if active.exists():shutil.rmtree(active)
   os.replace(folder,active);size=sum(x["bytes"] for x in manifest["files"]);set_state(mid,status="installed",received_bytes=size,total_bytes=size,installed_at=now(),error=None)
   audit("installed",mid)
  except Paused:set_state(mid,status="paused",speed_bps=0)
  except Exception as e:set_state(mid,status="failed",speed_bps=0,error=str(e));audit("install_failed",mid,str(e))
 def _validate_decision_bundle(self,spec,folder):
  names={str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file()}
  if spec.engine == "gliner2_5_multi_decide" and ("config.json" not in names or not any(name.endswith(".safetensors") for name in names)):
   raise ValueError("GLiNER2.5 decision bundle requires config.json and safetensors weights")
  if spec.engine == "laya_multilingual" and ({"rl_agent_config.json","encoder/config.json","tokenizer/tokenizer.json"} - names or not any(name.endswith(".safetensors") for name in names)):
   raise ValueError("Laya decision bundle requires agent, encoder, tokenizer, and safetensors artifacts")
  if any(name.endswith((".bin",".pt",".pkl",".pickle")) for name in names):
   raise ValueError("unsafe decision bundle artifact")
  for path in folder.rglob("*.json"):
   config=json.loads(path.read_text())
   if config.get("auto_map") or config.get("trust_remote_code"):
    raise ValueError("decision bundles may not require remote code")
  script = (
   "from gliner2 import GLiNER2; GLiNER2.from_pretrained(__import__('sys').argv[1])"
   if spec.engine == "gliner2_5_multi_decide" else
   "import laya; laya.load(__import__('sys').argv[1], device='cpu')"
  )
  env={**os.environ,"HF_HUB_OFFLINE":"1","TRANSFORMERS_OFFLINE":"1"}
  result=subprocess.run([os.sys.executable,"-c",script,str(folder)],text=True,capture_output=True,env=env,timeout=60)
  if result.returncode:
   raise ValueError("decision smoke failed: "+(result.stderr or result.stdout)[-1000:])
 def _file(self,mid,f,folder,stop,bundle_received,bundle_total):
  if requests is None:raise RuntimeError("requests is required to download model artifacts")
  final=folder/f.filename;part=folder/(f.filename+".part")
  final.parent.mkdir(parents=True,exist_ok=True)
  if final.exists():return bundle_received+final.stat().st_size
  offset=part.stat().st_size if part.exists() else 0
  for attempt in range(5):
   if stop.is_set():raise Paused()
   headers={"User-Agent":"Persian-ASR/2.0",**({"Range":f"bytes={offset}-"} if offset else {})}
   try:
    response=download_session().get(f.url,headers=headers,timeout=(15,30),stream=True)
    if response.status_code>=400:response.raise_for_status()
    if offset and response.status_code!=206:part.unlink(missing_ok=True);offset=0;response.close();continue
    length=int(response.headers.get("Content-Length","0"));total=max(bundle_total,bundle_received+length);started=time.monotonic();start=offset;last=started
    with part.open("ab" if offset else "wb") as out:
     for chunk in response.iter_content(1024*1024):
      if not chunk:continue
      if stop.is_set():raise Paused()
      out.write(chunk);offset+=len(chunk);tick=time.monotonic()
      if tick-last>=.3:set_state(mid,status="downloading",received_bytes=bundle_received-start+offset,total_bytes=total,speed_bps=(offset-start)/max(tick-started,.001));last=tick
    os.replace(part,final);return bundle_received-start+offset
   except requests.HTTPError as e:
    code=e.response.status_code
    if code==416 and attempt==0:part.unlink(missing_ok=True);offset=0;continue
    if code in (429,500,502,503,504):time.sleep(min(2**attempt,16));continue
    raise RuntimeError(f"HTTP {code}: {f.filename}")
   except requests.RequestException:
    if attempt==4:raise
    time.sleep(min(2**attempt,16));offset=part.stat().st_size if part.exists() else 0
  raise RuntimeError(f"download failed: {f.filename}")
manager=DownloadManager()
