"""Durable sequential multi-model task orchestration."""

import hashlib, json, logging, os, random, subprocess, sys, tempfile, threading, time, traceback, uuid
from contextlib import closing, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from asr_service.infrastructure.storage import (
    DATA_DIR,
    connect,
    execute,
    now,
    row,
    rows,
)
from asr_service.infrastructure.failures import record_failure
from .inference import NoSpeechDetectedError, transcribe
from .text_processing import chat_completion, process as process_text, process_messages, process_response
from asr_service.infrastructure.ninerouter import NineRouterClient, NineRouterError, resolve_settings
from .resources import DECISION_MAX_CONCURRENT, LLM_MAX_CONCURRENT, TASK_WORKERS, admission_allowed, inference_slot
from . import object_storage
from .audio_compression import decompress_gzip
from .ingress import ensure_spool_capacity

logger = logging.getLogger(__name__)

TASK_DIR = DATA_DIR / "tasks"
WORKERS = TASK_WORKERS
QUEUE_LIMIT = max(WORKERS, int(os.getenv("ASR_QUEUE_LIMIT", "100")))
DECISION_QUEUE_LIMIT = max(1, int(os.getenv("ASR_DECISION_QUEUE_LIMIT", "256")))
QUEUE_MAX_AUDIO_BYTES = max(
    1, int(os.getenv("ASR_QUEUE_MAX_AUDIO_MB", "8192"))
) * 1024 * 1024
QUEUE_MAX_MODEL_RUNS = max(
    QUEUE_LIMIT, int(os.getenv("ASR_QUEUE_MAX_MODEL_RUNS", str(QUEUE_LIMIT * 2)))
)
MAX_ATTEMPTS = max(1, int(os.getenv("ASR_TASK_MAX_ATTEMPTS", "2")))
MAX_MODELS = max(1, int(os.getenv("ASR_MAX_MODELS_PER_TASK", "5")))
STALE_SECONDS = max(60, int(os.getenv("ASR_TASK_STALE_SECONDS", "120")))
RESULT_TTL_HOURS = max(1, int(os.getenv("ASR_TASK_RESULT_TTL_HOURS", "168")))
CHAT_TASK_TIMEOUT_SECONDS = max(121, int(os.getenv("ASR_CHAT_TASK_TIMEOUT_SECONDS", "900")))
POLL_SECONDS = max(0.1, float(os.getenv("ASR_TASK_POLL_SECONDS", ".5")))
TERMINAL = {"succeeded", "partially_succeeded", "failed", "cancelled"}
RUN_TERMINAL = {"succeeded", "failed", "cancelled", "skipped"}


def get_task(task_id):
    return row("SELECT * FROM tasks WHERE task_id=?", (task_id,))


def get_runs(task_id):
    return rows("SELECT * FROM task_runs WHERE task_id=? ORDER BY position", (task_id,))


def scoped_idempotency_key(key, api_key_id=None):
    """Namespace caller-provided keys so different customers cannot collide."""
    return (
        f"{api_key_id if api_key_id is not None else 'legacy'}:{key}" if key else None
    )


def get_by_key(key, api_key_id=None):
    if not key:
        return None
    scoped = scoped_idempotency_key(key, api_key_id)
    found = row("SELECT * FROM tasks WHERE idempotency_key=?", (scoped,))
    if found:
        return found
    # Compatibility for tasks created before keys were namespaced.
    return row(
        "SELECT * FROM tasks WHERE idempotency_key=? AND api_key_id IS ?",
        (key, api_key_id),
    )


def queue_depth():
    return row(
        "SELECT count(*) n FROM tasks WHERE status IN ('queued','retrying','running')"
    )["n"]


def cancel_all_active():
    """Persistently cancel every queued or executing asynchronous task.

    Native ASR/LLM calls cannot be safely interrupted from a Python thread.
    This function records cancellation before the administrator-triggered
    process restart, so the replacement worker starts with a clean queue.
    """
    stamp = now()
    with closing(connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        active = [
            dict(item)
            for item in db.execute(
                "SELECT task_id,usage_id,input_path FROM tasks "
                "WHERE status IN ('queued','retrying','running')"
            ).fetchall()
        ]
        chat_usage = [
            item["id"]
            for item in db.execute(
                """SELECT id FROM usage u WHERE filename='chat.completions'
                   AND status IN ('queued','processing')
                   AND NOT EXISTS(SELECT 1 FROM tasks t WHERE t.usage_id=u.id)"""
            ).fetchall()
        ]
        if not active and not chat_usage:
            return []
        ids = [item["task_id"] for item in active]
        if ids:
            marks = ",".join("?" for _ in ids)
            db.execute(
                f"UPDATE tasks SET status='cancelled',cancel_requested=1,finished_at=?,"
                f"updated_at=?,worker_id=NULL,heartbeat_at=NULL,error='Interrupted by administrator' "
                f"WHERE task_id IN ({marks})",
                (stamp, stamp, *ids),
            )
            db.execute(
                f"UPDATE task_runs SET status=CASE WHEN status='processing' THEN 'cancelled' ELSE 'skipped' END,"
                f"finished_at=?,updated_at=?,worker_id=NULL,heartbeat_at=NULL,error='Interrupted by administrator' "
                f"WHERE task_id IN ({marks}) AND status IN ('pending','retrying','processing')",
                (stamp, stamp, *ids),
            )
        usage_ids = [item["usage_id"] for item in active if item.get("usage_id")]
        if usage_ids:
            usage_marks = ",".join("?" for _ in usage_ids)
            db.execute(
                f"UPDATE usage SET status='failed',finished_at=?,error='Interrupted by administrator' "
                f"WHERE id IN ({usage_marks})",
                (stamp, *usage_ids),
            )
        if chat_usage:
            chat_marks = ",".join("?" for _ in chat_usage)
            db.execute(
                f"UPDATE usage SET status='failed',finished_at=?,error='Interrupted by administrator' "
                f"WHERE id IN ({chat_marks})",
                (stamp, *chat_usage),
            )
    for item in active:
        log_task(item["task_id"], "Interrupted by administrator; service is restarting", "warning", "cancelled")
    return active


def recover_interrupted_chat_completions():
    """Close synchronous OpenAI usage rows left by a process restart."""
    stamp = now()
    with closing(connect()) as db, db:
        return db.execute(
            """UPDATE usage SET status='failed',finished_at=?,
               error='Service restarted before chat completion finished'
               WHERE filename='chat.completions' AND status IN ('queued','processing')
               AND NOT EXISTS(SELECT 1 FROM tasks t WHERE t.usage_id=usage.id)""",
            (stamp,),
        ).rowcount


def fingerprint(kind, models, input_data, response_format, content_sha256=None):
    payload = {
        "kind": kind,
        "models": models,
        "input": input_data or {},
        "response_format": response_format,
        "content_sha256": content_sha256,
    }
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _remote_key(input_path):
    return input_path[5:] if input_path and input_path.startswith("s3://") else None


def _delete_input(input_path):
    """Remove either a durable local spool file or its private S3 object."""
    key = _remote_key(input_path)
    try:
        if key:
            object_storage.delete(key)
            execute(
                "UPDATE uploads SET status='deleted',updated_at=? WHERE object_key=? AND status='scheduled'",
                (now(), key),
            )
        elif input_path:
            Path(input_path).unlink(missing_ok=True)
    except Exception:
        # Cleanup must never invalidate an already-completed task result.
        pass


def _materialize_input(task):
    """Return a local file ready for native inference and whether it is temporary."""
    key = _remote_key(task.get("input_path"))
    if not key:
        return task["input_path"], False
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(task.get("filename") or "audio").suffix
    handle = tempfile.NamedTemporaryFile(dir=TASK_DIR, suffix=suffix, delete=False)
    local_path = handle.name
    handle.close()
    try:
        data = json.loads(task.get("input_json") or "{}")
        encoded_path = local_path
        if data.get("audio_encoding") == "gzip":
            encoded_path = f"{local_path}.gz"
            Path(local_path).unlink(missing_ok=True)
        size, digest = object_storage.download(key, encoded_path)
        expected_encoded_size = data.get("compressed_audio_bytes") or task.get("audio_bytes")
        if size != expected_encoded_size:
            raise ValueError("Downloaded object size does not match task metadata")
        expected = data.get("sha256")
        if expected and digest != expected:
            raise ValueError("Downloaded object SHA-256 does not match upload declaration")
        if data.get("audio_encoding") == "gzip":
            with open(encoded_path, "rb") as source, open(local_path, "wb") as output:
                result = decompress_gzip(
                    source, output, maximum_bytes=QUEUE_MAX_AUDIO_BYTES,
                    expected_bytes=data.get("uncompressed_audio_bytes"),
                    on_progress=lambda decoded: ensure_spool_capacity(
                        TASK_DIR, max(0, decoded - task.get("audio_bytes", 0))
                    ),
                )
            Path(encoded_path).unlink(missing_ok=True)
            if result["audio_bytes"] != task.get("audio_bytes"):
                raise ValueError("Uncompressed audio size does not match task metadata")
        return local_path, True
    except Exception:
        Path(local_path).unlink(missing_ok=True)
        Path(f"{local_path}.gz").unlink(missing_ok=True)
        raise


def _event(table, key, value, message, level="info", event_type="message"):
    try:
        stamp = now()
        if table == "task_events":
            task = get_task(value)
            if not task:
                return
            execute(
                "INSERT INTO task_events(task_id,usage_id,created_at,level,event_type,message) VALUES(?,?,?,?,?,?)",
                (
                    value,
                    task["usage_id"],
                    stamp,
                    level,
                    event_type,
                    str(message)[:16000],
                ),
            )
        else:
            execute(
                f"INSERT INTO {table}({key},created_at,level,event_type,message) VALUES(?,?,?,?,?)",
                (value, stamp, level, event_type, str(message)[:16000]),
            )
        # Keep the legacy aggregate log populated during the compatibility window.
        with closing(connect()) as db, db:
            if table == "task_events":
                usage = db.execute(
                    "SELECT u.id,u.execution_log FROM usage u JOIN tasks t ON t.usage_id=u.id WHERE t.task_id=?",
                    (value,),
                ).fetchone()
            else:
                usage = db.execute(
                    "SELECT u.id,u.execution_log FROM usage u JOIN tasks t ON t.usage_id=u.id JOIN task_runs r ON r.task_id=t.task_id WHERE r.id=?",
                    (value,),
                ).fetchone()
            if usage:
                events = json.loads(usage["execution_log"] or "[]")
                events.append({"at": stamp, "message": str(message)[:16000]})
                db.execute(
                    "UPDATE usage SET execution_log=? WHERE id=?",
                    (json.dumps(events, ensure_ascii=False), usage["id"]),
                )
    except Exception:
        pass


def log_task(task_id, message, level="info", event_type="message"):
    task = get_task(task_id)
    if task:
        _event("task_events", "task_id", task_id, message, level, event_type)


def log_run(run_id, message, level="info", event_type="message"):
    _event("task_run_events", "run_id", run_id, message, level, event_type)


def public_task(task, include_result=True):
    if not task:
        return None
    runs = get_runs(task["task_id"])
    models = [x["model_id"] for x in runs] or [task["model_id"]]
    out = {
        k: task.get(k)
        for k in (
            "task_id",
            "kind",
            "status",
            "created_at",
            "started_at",
            "finished_at",
            "updated_at",
            "model_id",
            "filename",
            "response_format",
            "attempts",
            "max_attempts",
            "duration_seconds",
            "processing_seconds",
            "error",
        )
    }
    if runs:
        out["attempts"] = sum(x["attempts"] for x in runs)
        out["max_attempts"] = sum(x["max_attempts"] for x in runs)
    out.update(
        models=models,
        current_model=next(
            (x["model_id"] for x in runs if x["status"] in {"processing", "retrying"}),
            None,
        ),
        completed_models=sum(x["status"] in RUN_TERMINAL for x in runs),
        total_models=len(models),
    )
    has_result = task["status"] in {"succeeded", "partially_succeeded"} or (
        len(runs) > 1 and task["status"] == "failed" and task.get("result_json")
    )
    out["status_url"] = f"/v1/tasks/{task['task_id']}"
    out["result_url"] = (f"/v1/tasks/{task['task_id']}/result"
                         if has_result or task["kind"] == "chat_async" else None)
    if task["kind"] == "chat_async":
        out["status"] = "queued" if task["status"] == "retrying" else task["status"]
        out["error_code"] = ("task_timeout" if task["status"] == "failed" and any(x.get("error") == "task_timeout" for x in runs)
                             else "model_failure" if task["status"] == "failed"
                             else "task_cancelled" if task["status"] == "cancelled" else None)
    if include_result and has_result:
        out["result"] = json.loads(task["result_json"])
    return out


def enqueue(
    kind,
    model_id=None,
    models=None,
    input_path=None,
    input_data=None,
    response_format="json",
    filename=None,
    client_ip=None,
    idempotency_key=None,
    audio_bytes=0,
    request_fingerprint=None,
    api_key_id=None,
):
    ordered = list(models or ([model_id] if model_id else []))
    if not ordered or len(ordered) > MAX_MODELS or len(set(ordered)) != len(ordered):
        raise ValueError("Invalid ordered model list")
    task_id = uuid.uuid4().hex
    stamp = now()
    stored_idempotency_key = scoped_idempotency_key(idempotency_key, api_key_id)
    try:
        with closing(connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                existing = db.execute(
                    "SELECT * FROM tasks WHERE idempotency_key=?",
                    (stored_idempotency_key,),
                ).fetchone()
                if not existing:
                    existing = db.execute(
                        "SELECT * FROM tasks WHERE idempotency_key=? AND api_key_id IS ?",
                        (idempotency_key, api_key_id),
                    ).fetchone()
                if existing:
                    existing = dict(existing)
                    if (
                        existing.get("request_fingerprint")
                        and request_fingerprint
                        and existing["request_fingerprint"] != request_fingerprint
                    ):
                        raise IdempotencyConflict()
                    return existing, False
            if (
                db.execute(
                    "SELECT count(*) n FROM tasks WHERE status IN ('queued','retrying','running')"
                ).fetchone()["n"]
                >= QUEUE_LIMIT
            ):
                raise OverflowError("Task queue is full")
            if kind == "decision" and db.execute(
                "SELECT count(*) n FROM tasks WHERE kind='decision' AND status IN ('queued','retrying','running')"
            ).fetchone()["n"] >= DECISION_QUEUE_LIMIT:
                raise OverflowError("Decision task queue is full")
            active_audio = db.execute(
                "SELECT coalesce(sum(audio_bytes),0) n FROM tasks "
                "WHERE status IN ('queued','retrying','running') AND kind='asr'"
            ).fetchone()["n"]
            if active_audio + audio_bytes > QUEUE_MAX_AUDIO_BYTES:
                raise OverflowError("Task queue audio capacity is full")
            active_runs = db.execute(
                "SELECT count(*) n FROM task_runs r JOIN tasks t ON t.task_id=r.task_id "
                "WHERE t.status IN ('queued','retrying','running')"
            ).fetchone()["n"]
            if active_runs + len(ordered) > QUEUE_MAX_MODEL_RUNS:
                raise OverflowError("Task queue model-run capacity is full")
            initial_log = json.dumps(
                [
                    {
                        "at": stamp,
                        "message": f"Request accepted and queued with {len(ordered)} model(s): {', '.join(ordered)}",
                    }
                ],
                ensure_ascii=False,
            )
            usage_id = db.execute(
                "INSERT INTO usage(created_at,model_id,filename,status,response_format,client_ip,audio_bytes,execution_log) VALUES(?,?,?,?,?,?,?,?)",
                (
                    stamp,
                    ordered[0],
                    filename,
                    "queued",
                    response_format,
                    client_ip,
                    audio_bytes,
                    initial_log,
                ),
            ).lastrowid
            db.execute(
                """INSERT INTO tasks(task_id,kind,status,created_at,available_at,updated_at,model_id,input_path,input_json,response_format,filename,client_ip,idempotency_key,request_fingerprint,max_attempts,audio_bytes,usage_id,api_key_id) VALUES(?,?,'queued',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    kind,
                    stamp,
                    stamp,
                    stamp,
                    ordered[0],
                    input_path,
                    json.dumps(input_data, ensure_ascii=False) if input_data else None,
                    response_format,
                    filename,
                    client_ip,
                    stored_idempotency_key,
                    request_fingerprint,
                    MAX_ATTEMPTS,
                    audio_bytes,
                    usage_id,
                    api_key_id,
                ),
            )
            db.executemany(
                "INSERT INTO task_runs(task_id,usage_id,position,model_id,status,max_attempts,available_at,updated_at) VALUES(?,?,?,?,'pending',?,?,?)",
                [
                    (task_id, usage_id, i, mid, MAX_ATTEMPTS, stamp, stamp)
                    for i, mid in enumerate(ordered)
                ],
            )
            db.execute(
                "INSERT INTO task_events(task_id,usage_id,created_at,event_type,message) VALUES(?,?,?,?,?)",
                (
                    task_id,
                    usage_id,
                    stamp,
                    "queued",
                    f"Request accepted with {len(ordered)} model(s): {', '.join(ordered)}",
                ),
            )
    except (OverflowError, IdempotencyConflict):
        raise
    except Exception:
        if idempotency_key:
            existing = get_by_key(idempotency_key, api_key_id)
            if existing:
                if (
                    existing.get("request_fingerprint")
                    and request_fingerprint
                    and existing["request_fingerprint"] != request_fingerprint
                ):
                    raise IdempotencyConflict()
                return existing, False
        raise
    return get_task(task_id), True


def serialize_run(run, response_format="verbose_json"):
    result = json.loads(run["result_json"]) if run.get("result_json") else None
    content_type = "application/json"
    if result and "text" in result:
        if response_format == "json":
            result = {"text": result["text"]}
        elif response_format == "text":
            result = result["text"]
            content_type = "text/plain"
        elif response_format in {"srt", "vtt"}:

            def stamp(seconds, decimal):
                milliseconds = round(seconds * 1000)
                hours, milliseconds = divmod(milliseconds, 3600000)
                minutes, milliseconds = divmod(milliseconds, 60000)
                seconds, milliseconds = divmod(milliseconds, 1000)
                return f"{hours:02}:{minutes:02}:{seconds:02}{decimal}{milliseconds:03}"

            blocks = []
            for index, segment in enumerate(result.get("segments", []), 1):
                blocks.append(
                    ("" if response_format == "vtt" else f"{index}\n")
                    + f"{stamp(segment['start'],'.' if response_format=='vtt' else ',')} --> {stamp(segment['end'],'.' if response_format=='vtt' else ',')}\n{segment['text']}"
                )
            result = (
                ("WEBVTT\n\n" if response_format == "vtt" else "")
                + "\n\n".join(blocks)
                + "\n"
            )
            content_type = (
                "text/vtt" if response_format == "vtt" else "application/x-subrip"
            )
    return {
        "position": run["position"] + 1,
        "model": run["model_id"],
        "status": run["status"],
        "attempts": run["attempts"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "duration_seconds": run.get("duration_seconds"),
        "processing_seconds": run.get("processing_seconds"),
        "content_type": content_type,
        "result": result,
        "error": run.get("error"),
    }


class TaskManager:
    def __init__(self):
        self.stop_event = threading.Event()
        self.threads = []
        self.instance = uuid.uuid4().hex[:12]
        self.next_chat_expiry = 0

    def _expire_chat_tasks(self):
        """Purge private chat results and idempotency keys past retention."""
        expiry = (datetime.now(timezone.utc) - timedelta(hours=RESULT_TTL_HOURS)).isoformat()
        with closing(connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE task_runs SET result_json=NULL WHERE task_id IN
                   (SELECT task_id FROM tasks WHERE kind='chat_async'
                    AND status IN ('succeeded','failed','cancelled') AND finished_at<?)""",
                (expiry,),
            )
            db.execute(
                """DELETE FROM tasks WHERE kind='chat_async'
                   AND status IN ('succeeded','failed','cancelled') AND finished_at<?""",
                (expiry,),
            )

    def start(self):
        TASK_DIR.mkdir(parents=True, exist_ok=True)
        self._recover()
        for i in range(WORKERS):
            thread = threading.Thread(
                target=self._loop, args=(f"{self.instance}-{i}",), daemon=True
            )
            thread.start()
            self.threads.append(thread)

    def stop(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=5)

    def _recover(self):
        # Startup occurs before this process starts workers, so every processing lease belongs to a dead process.
        recover_interrupted_chat_completions()
        self._expire_chat_tasks()
        for run in rows(
            "SELECT id,task_id,attempts,max_attempts FROM task_runs WHERE status='processing' AND task_id IS NOT NULL"
        ):
            if run["attempts"] < run["max_attempts"]:
                execute(
                    "UPDATE task_runs SET status='retrying',worker_id=NULL,available_at=?,updated_at=?,error='Worker interrupted; run recovered' WHERE id=?",
                    (now(), now(), run["id"]),
                )
                execute(
                    "UPDATE tasks SET status='retrying',worker_id=NULL,available_at=?,updated_at=? WHERE task_id=?",
                    (now(), now(), run["task_id"]),
                )
                log_run(
                    run["id"],
                    "Worker interrupted; model run recovered",
                    "warning",
                    "recovered",
                )
            else:
                execute(
                    "UPDATE task_runs SET status='failed',finished_at=?,updated_at=?,worker_id=NULL,heartbeat_at=NULL,error='Worker interrupted on final attempt' WHERE id=?",
                    (now(), now(), run["id"]),
                )
                log_run(
                    run["id"],
                    "Worker interrupted on final attempt; run marked failed",
                    "error",
                    "failed",
                )
        # Repair crashes between committing a run and advancing/finalizing its parent.
        for task in rows("SELECT task_id FROM tasks WHERE status='running'"):
            runs = get_runs(task["task_id"])
            if any(x["status"] in {"pending", "retrying"} for x in runs):
                execute(
                    "UPDATE tasks SET status='queued',worker_id=NULL,heartbeat_at=NULL,available_at=?,updated_at=? WHERE task_id=?",
                    (now(), now(), task["task_id"]),
                )
            elif runs and all(x["status"] in RUN_TERMINAL for x in runs):
                self._finish_parent(task["task_id"])
        expiry = (
            datetime.now(timezone.utc) - timedelta(hours=RESULT_TTL_HOURS)
        ).isoformat()
        for old in rows(
            "SELECT input_path FROM tasks WHERE status IN ('succeeded','partially_succeeded','failed','cancelled') AND finished_at<? AND input_path IS NOT NULL",
            (expiry,),
        ):
            _delete_input(old["input_path"])
        execute(
            "DELETE FROM tasks WHERE status IN ('succeeded','partially_succeeded','failed','cancelled') AND finished_at<?",
            (expiry,),
        )
        # A browser can disappear mid-upload. Abort unfinished multipart
        # sessions and delete completed-but-never-scheduled objects so private
        # object storage cannot grow without bound.
        for upload in rows(
            "SELECT upload_id,status,object_key,backend_upload_id FROM uploads WHERE status IN ('uploading','completed') AND expires_at<?",
            (now(),),
        ):
            try:
                if upload["status"] == "uploading" and upload["backend_upload_id"]:
                    object_storage.abort_multipart(upload["object_key"], upload["backend_upload_id"])
                elif upload["status"] == "completed":
                    object_storage.delete(upload["object_key"])
            except Exception:
                # Retry cleanup during the next service restart; the DB record
                # remains actionable rather than incorrectly claiming deletion.
                continue
            execute("UPDATE uploads SET status='expired',updated_at=? WHERE upload_id=?", (now(), upload["upload_id"]))
        referenced = {
            str(Path(x["input_path"]))
            for x in rows("SELECT input_path FROM tasks WHERE input_path IS NOT NULL")
        }
        orphan_cutoff = time.time() - STALE_SECONDS
        TASK_DIR.mkdir(parents=True, exist_ok=True)
        for candidate in TASK_DIR.iterdir():
            try:
                if (
                    candidate.is_file()
                    and str(candidate) not in referenced
                    and candidate.stat().st_mtime < orphan_cutoff
                ):
                    candidate.unlink(missing_ok=True)
            except OSError:
                pass

    def _claim(self, worker):
        stamp = now()
        with closing(connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            # Select a task only when its *next* model run is ready. Selecting
            # the oldest parent task first used to let a retry backoff block all
            # newer ready work and left CPU capacity idle.
            task = db.execute(
                """SELECT t.task_id FROM tasks t
                   WHERE t.status IN ('queued','retrying') AND t.available_at<=?
                   AND (
                     -- ASR and LLM work share the same inference slots and
                     -- are dispatched in arrival order.  Do not make audio
                     -- wait for every active LLM request.
                     t.kind='asr'
                     OR
                     -- Keep the separate LLM pool bounded: each llama.cpp
                     -- context has its own substantial memory footprint.
                     (t.kind IN ('chat','chat_async','text') AND (
                       SELECT count(*) FROM tasks active_llm
                       WHERE active_llm.status='running' AND active_llm.kind IN ('chat','chat_async','text')
                     ) < ?)
                     OR
                     (t.kind='decision' AND (
                       SELECT count(*) FROM tasks active_decision
                       WHERE active_decision.status='running' AND active_decision.kind='decision'
                     ) < ?)
                   )
                   AND EXISTS(
                     SELECT 1 FROM task_runs r WHERE r.task_id=t.task_id
                     AND r.status IN ('pending','retrying') AND r.available_at<=?
                     AND r.position=(SELECT min(first_run.position) FROM task_runs first_run
                                     WHERE first_run.task_id=t.task_id
                                     AND first_run.status IN ('pending','retrying'))
                   )
                   ORDER BY t.created_at, t.rowid LIMIT 1""",
                (stamp, LLM_MAX_CONCURRENT, DECISION_MAX_CONCURRENT, stamp),
            ).fetchone()
            if not task:
                return None
            run = db.execute(
                "SELECT * FROM task_runs WHERE task_id=? AND status IN ('pending','retrying') AND available_at<=? ORDER BY position LIMIT 1",
                (task["task_id"], stamp),
            ).fetchone()
            if not run or run["available_at"] > stamp:
                return None
            if not db.execute(
                "UPDATE task_runs SET status='processing',worker_id=?,started_at=coalesce(started_at,?),attempt_started_at=?,heartbeat_at=?,updated_at=?,attempts=attempts+1 WHERE id=? AND status IN ('pending','retrying')",
                (worker, stamp, stamp, stamp, stamp, run["id"]),
            ).rowcount:
                return None
            db.execute(
                "UPDATE tasks SET status='running',worker_id=?,started_at=coalesce(started_at,?),heartbeat_at=?,updated_at=?,attempts=attempts+1 WHERE task_id=?",
                (worker, stamp, stamp, stamp, task["task_id"]),
            )
            claimed = dict(
                db.execute(
                    "SELECT * FROM tasks WHERE task_id=?", (task["task_id"],)
                ).fetchone()
            )
            claimed["run"] = dict(
                db.execute(
                    "SELECT * FROM task_runs WHERE id=?", (run["id"],)
                ).fetchone()
            )
            if claimed.get("usage_id"):
                db.execute(
                    "UPDATE usage SET status='processing' WHERE id=?",
                    (claimed["usage_id"],),
                )
            return claimed

    def _loop(self, worker):
        while not self.stop_event.is_set():
            if worker.endswith("-0") and time.monotonic() >= self.next_chat_expiry:
                self.next_chat_expiry = time.monotonic() + 3600
                try:
                    self._expire_chat_tasks()
                except Exception:
                    logger.exception("Unable to expire completed chat tasks")
            # Do not start a new job merely because a numerical slot is free:
            # preserve CPU/RAM headroom for the OS and already-running jobs.
            if not admission_allowed(queue_depth() > 0):
                self.stop_event.wait(POLL_SECONDS)
                continue
            # Admission happens before claiming the task. A task therefore is
            # never presented as running while merely waiting for CPU capacity.
            slot = inference_slot(timeout=0)
            try:
                slot.__enter__()
            except InferenceCapacityError:
                self.stop_event.wait(POLL_SECONDS)
                continue
            try:
                task = self._claim(worker)
            except Exception:
                # This is a scheduler/database failure, not a task failure,
                # so it has no task id to attach to the dashboard.  It must
                # still be visible in the service logs.
                logger.exception("Unable to claim the next queued task")
                task = None
            if not task:
                slot.__exit__(None, None, None)
                self.stop_event.wait(POLL_SECONDS)
                continue
            try:
                self._run(task, slot)
            finally:
                slot.__exit__(None, None, None)

    def _finish_parent(self, task_id):
        task = get_task(task_id)
        runs = get_runs(task_id)
        if any(x["status"] not in RUN_TERMINAL for x in runs):
            execute(
                "UPDATE tasks SET status='queued',available_at=?,updated_at=?,worker_id=NULL,heartbeat_at=NULL WHERE task_id=?",
                (now(), now(), task_id),
            )
            return
        succeeded = sum(x["status"] == "succeeded" for x in runs)
        status = (
            "cancelled"
            if task.get("cancel_requested") and not succeeded
            else (
                "succeeded"
                if succeeded == len(runs)
                else "partially_succeeded" if succeeded else "failed"
            )
        )
        results = [serialize_run(x, task["response_format"]) for x in runs]
        result = (
            results[0]["result"]
            if len(results) == 1 and status == "succeeded"
            else {"task_id": task_id, "status": status, "results": results}
        )
        content_type = (
            results[0]["content_type"]
            if len(results) == 1 and status == "succeeded"
            else "application/json"
        )
        total = sum(x.get("processing_seconds") or 0 for x in runs)
        duration = next(
            (
                x.get("duration_seconds")
                for x in runs
                if x.get("duration_seconds") is not None
            ),
            None,
        )
        errors = [f"{x['model_id']}: {x['error']}" for x in runs if x.get("error")]
        stamp = now()
        error_text = "\n".join(errors)[:4000] or None
        usage_status = (
            "success"
            if status == "succeeded"
            else "partial_success" if status == "partially_succeeded" else "failed"
        )
        with closing(connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE tasks SET status=?,finished_at=?,updated_at=?,result_json=?,duration_seconds=?,processing_seconds=?,error=?,worker_id=NULL,heartbeat_at=NULL WHERE task_id=?",
                (
                    status,
                    stamp,
                    stamp,
                    json.dumps(result, ensure_ascii=False),
                    duration,
                    total,
                    error_text,
                    task_id,
                ),
            )
            # Keep the final payload on the history row as well as on the task.
            # The dashboard reads history independently, so omitting this made a
            # successful processing result impossible to open from that screen.
            db.execute(
                """UPDATE usage SET status=?,finished_at=?,duration_seconds=?,
                   processing_seconds=?,error=?,result_json=?,content_type=? WHERE id=?""",
                (
                    usage_status,
                    stamp,
                    duration,
                    total,
                    error_text,
                    None if task["kind"] == "chat_async" else json.dumps(result, ensure_ascii=False),
                    content_type,
                    task.get("usage_id"),
                ),
            )
        log_task(
            task_id,
            f"Task finished with status {status}",
            "info" if status == "succeeded" else "warning" if status == "partially_succeeded" else "error",
            "finished",
        )
        if status != "succeeded":
            record_failure(
                phase="processing",
                reason={
                    "partially_succeeded": "task_partially_succeeded",
                    "cancelled": "task_cancelled",
                }.get(status, "task_failed"),
                detail=error_text or f"Task finished with status {status}",
                task_id=task_id,
                usage_id=task.get("usage_id"),
                client_ip=task.get("client_ip"),
                dedupe_key=f"task:{task_id}:{status}",
            )

    def _run(self, task, admitted_slot=None):
        run = task["run"]
        started = time.monotonic()
        task_id = task["task_id"]
        log_run(
            run["id"],
            f"Started attempt {run['attempts']} of {run['max_attempts']}",
            event_type="started",
        )
        stop = threading.Event()

        def heartbeat():
            while not stop.wait(10):
                stamp = now()
                with closing(connect()) as db, db:
                    db.execute(
                        "UPDATE task_runs SET heartbeat_at=?,updated_at=? WHERE id=? AND status='processing'",
                        (stamp, stamp, run["id"]),
                    )
                    db.execute(
                        "UPDATE tasks SET heartbeat_at=?,updated_at=? WHERE task_id=? AND status='running'",
                        (stamp, stamp, task_id),
                    )

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            if task["cancel_requested"]:
                raise CancelledError()
            args = json.loads(task["input_json"] or "{}")
            provider = resolve_settings()
            if task["kind"] == "asr":
                with (nullcontext() if admitted_slot else inference_slot()):
                    local_input, temporary_input = _materialize_input(task)
                    try:
                        if provider.asr_enabled and run["model_id"] == provider.asr_model:
                            log_run(run["id"], "Submitting audio to 9Router")
                            result = NineRouterClient(provider).transcribe(run["model_id"], local_input, args.get("prompt"))
                        else:
                            text, segments, duration, duration_vad = transcribe(
                                local_input, run["model_id"], args.get("beam_size", 2), args.get("vad_filter", True),
                                args.get("prompt"), lambda message: log_run(run["id"], message),
                            )
                            result = {"text": text, "language": "fa", "duration": duration, "duration_after_vad": duration_vad, "model": run["model_id"], "segments": segments}
                    finally:
                        if temporary_input:
                            Path(local_input).unlink(missing_ok=True)
                duration = result.get("duration")
                duration_vad = result.get("duration_after_vad")
            elif task["kind"] == "text":
                with (nullcontext() if admitted_slot else inference_slot()):
                    if provider.text_enabled and run["model_id"] == provider.text_model:
                        messages, options = process_messages(args.get("text"), args["operation"], args["style"], args.get("segments"), args.get("prompt"))
                        completion = NineRouterClient(provider).chat(run["model_id"], messages, options)
                        content = completion["choices"][0].get("message", {}).get("content", "")
                        result = {"model": completion.get("model") or run["model_id"], "operation": args["operation"], **process_response(content, args["operation"], args["style"], args.get("segments")), "finish_reason": completion["choices"][0].get("finish_reason"), "usage": completion.get("usage")}
                    else:
                        result = {"model": run["model_id"], "operation": args["operation"], **process_text(run["model_id"], args.get("text"), args["operation"], args["style"], args.get("segments"), args.get("prompt"))}
                duration = duration_vad = None
            elif task["kind"] == "decision":
                with (nullcontext() if admitted_slot else inference_slot()):
                    from .decision_processing import decide
                    result = decide(run["model_id"], args["state"], args["questions"], args.get("confidence_threshold") or .72)
                duration = duration_vad = None
            elif task["kind"] == "chat":
                # Chat requests are executed by this durable worker too, so
                # they share the exact same persisted FIFO ordering as ASR and
                # text tasks.  Streaming is rendered only after this completed
                # result is stored; native generation never runs in an HTTP
                # request thread.
                with (nullcontext() if admitted_slot else inference_slot()):
                    result = NineRouterClient(provider).chat(run["model_id"], args["messages"], args["options"]) if provider.text_enabled and run["model_id"] == provider.text_model else chat_completion(run["model_id"], args["messages"], **args["options"])
                duration = duration_vad = None
            elif task["kind"] == "chat_async":
                if provider.text_enabled and run["model_id"] == provider.text_model:
                    result = NineRouterClient(provider).chat(run["model_id"], args["messages"], args["options"])
                    result.setdefault("id", "chatcmpl-" + uuid.uuid4().hex)
                    result.setdefault("object", "chat.completion")
                    result.setdefault("created", int(time.time()))
                    result["model"] = run["model_id"]
                    duration = duration_vad = None
                else:
                    payload = json.dumps({"model": run["model_id"], "messages": args["messages"],
                                          "options": args["options"]}, ensure_ascii=False)
                    with subprocess.Popen(
                        [sys.executable, "-m", "asr_service.services.chat_task_runner"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True,
                    ) as child:
                        try:
                            deadline = time.monotonic() + CHAT_TASK_TIMEOUT_SECONDS
                            sent = False
                            while True:
                                if (get_task(task_id) or {}).get("cancel_requested"):
                                    raise CancelledError()
                                try:
                                    output, _ = child.communicate(
                                        payload if not sent else None,
                                        timeout=min(2, max(0.01, deadline - time.monotonic())),
                                    )
                                    break
                                except subprocess.TimeoutExpired:
                                    sent = True
                                    if time.monotonic() >= deadline:
                                        raise ChatTaskTimeout() from None
                        except (ChatTaskTimeout, CancelledError):
                            child.kill()
                            child.communicate()
                            raise
                        if child.returncode:
                            raise ChatTaskModelFailure()
                    try:
                        result = json.loads(output)
                        if not isinstance(result, dict) or not isinstance(result.get("choices"), list):
                            raise ValueError("Invalid chat completion")
                    except (ValueError, TypeError):
                        raise ChatTaskModelFailure() from None
                    result.setdefault("id", "chatcmpl-" + uuid.uuid4().hex)
                    result.setdefault("object", "chat.completion")
                    result.setdefault("created", int(time.time()))
                    result["model"] = run["model_id"]
                    duration = duration_vad = None
            else:
                raise ValueError(f"Unsupported task kind: {task['kind']}")
            if (get_task(task_id) or {}).get("cancel_requested"):
                raise CancelledError()
            elapsed = time.monotonic() - started
            execute(
                "UPDATE task_runs SET status='succeeded',finished_at=?,updated_at=?,result_json=?,duration_seconds=?,duration_after_vad=?,processing_seconds=coalesce(processing_seconds,0)+?,worker_id=NULL,heartbeat_at=NULL,error=NULL WHERE id=?",
                (
                    now(),
                    now(),
                    json.dumps(result, ensure_ascii=False),
                    duration,
                    duration_vad,
                    elapsed,
                    run["id"],
                ),
            )
            log_run(
                run["id"],
                f"Completed successfully in {elapsed:.2f} seconds",
                event_type="finished",
            )
        except CancelledError:
            elapsed = time.monotonic() - started
            execute(
                "UPDATE task_runs SET status='cancelled',finished_at=?,updated_at=?,processing_seconds=?,worker_id=NULL,heartbeat_at=NULL,error='Cancelled' WHERE id=?",
                (now(), now(), elapsed, run["id"]),
            )
            execute(
                "UPDATE task_runs SET status='skipped',finished_at=?,updated_at=?,error='Skipped after cancellation' WHERE task_id=? AND status IN ('pending','retrying')",
                (now(), now(), task_id),
            )
            log_run(run["id"], "Model run was cancelled", "warning", "cancelled")
        except Exception as exc:
            elapsed = time.monotonic() - started
            current = row("SELECT * FROM task_runs WHERE id=?", (run["id"],))
            retry = (
                current
                and current["attempts"] < current["max_attempts"]
                and not (get_task(task_id) or {}).get("cancel_requested")
                and not isinstance(exc, NoSpeechDetectedError)
                and (not isinstance(exc, NineRouterError) or exc.retryable)
            )
            error = ("task_timeout" if isinstance(exc, ChatTaskTimeout) else "model_failure") if task["kind"] == "chat_async" else f"{type(exc).__name__}: {exc}"[:4000]
            log_run(run["id"], f"Attempt failed: {error}" if task["kind"] == "chat_async"
                    else f"Attempt failed: {error}\n{traceback.format_exc(limit=20)[:12000]}", "error", "failed")
            if retry:
                available = (
                    datetime.now(timezone.utc)
                    + timedelta(
                        seconds=min(60, 2 ** current["attempts"] + random.random())
                    )
                ).isoformat()
                execute(
                    "UPDATE task_runs SET status='retrying',available_at=?,updated_at=?,processing_seconds=coalesce(processing_seconds,0)+?,error=?,worker_id=NULL,heartbeat_at=NULL WHERE id=?",
                    (available, now(), elapsed, error, run["id"]),
                )
                execute(
                    "UPDATE tasks SET status='retrying',available_at=?,updated_at=?,worker_id=NULL,heartbeat_at=NULL WHERE task_id=?",
                    (available, now(), task_id),
                )
                log_run(
                    run["id"], f"Retry scheduled for {available}", "warning", "retrying"
                )
                return
            execute(
                "UPDATE task_runs SET status='failed',finished_at=?,updated_at=?,processing_seconds=coalesce(processing_seconds,0)+?,error=?,worker_id=NULL,heartbeat_at=NULL WHERE id=?",
                (now(), now(), elapsed, error, run["id"]),
            )
        finally:
            stop.set()
            thread.join(timeout=1)
        self._finish_parent(task_id)
        final = get_task(task_id)
        if final and final["status"] in TERMINAL and final["input_path"]:
            _delete_input(final["input_path"])


class CancelledError(Exception):
    pass


class ChatTaskTimeout(Exception):
    pass


class ChatTaskModelFailure(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


manager = TaskManager()
