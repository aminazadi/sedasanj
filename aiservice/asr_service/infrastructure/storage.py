"""SQLite persistence and runtime data-directory access."""

import os, sqlite3, threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.getenv("ASR_DATA_DIR", "/data"))
MODEL_DIR = Path(os.getenv("ASR_MODELS_DIR", str(DATA_DIR / "models")))
DB_PATH = DATA_DIR / "asr.sqlite3"
_lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as db, db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.executescript(
            """CREATE TABLE IF NOT EXISTS model_state(model_id TEXT PRIMARY KEY,status TEXT NOT NULL DEFAULT 'not_installed',received_bytes INTEGER DEFAULT 0,total_bytes INTEGER DEFAULT 0,speed_bps REAL DEFAULT 0,error TEXT,installed_at TEXT,updated_at TEXT,job_id TEXT);CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,finished_at TEXT,model_id TEXT,filename TEXT,status TEXT NOT NULL,duration_seconds REAL,processing_seconds REAL,audio_bytes INTEGER,response_format TEXT,error TEXT,client_ip TEXT,execution_log TEXT,result_json TEXT,content_type TEXT);CREATE INDEX IF NOT EXISTS usage_created_idx ON usage(created_at DESC);CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,action TEXT NOT NULL,model_id TEXT,detail TEXT);
CREATE TABLE IF NOT EXISTS tasks(
 task_id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,
 started_at TEXT,finished_at TEXT,available_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 model_id TEXT NOT NULL,input_path TEXT,input_json TEXT,result_json TEXT,error TEXT,
 response_format TEXT,filename TEXT,client_ip TEXT,idempotency_key TEXT UNIQUE,
 attempts INTEGER NOT NULL DEFAULT 0,max_attempts INTEGER NOT NULL DEFAULT 1,
 worker_id TEXT,heartbeat_at TEXT,cancel_requested INTEGER NOT NULL DEFAULT 0,usage_id INTEGER,
 audio_bytes INTEGER DEFAULT 0,duration_seconds REAL,processing_seconds REAL);
CREATE INDEX IF NOT EXISTS tasks_dispatch_idx ON tasks(status,available_at,created_at);
CREATE INDEX IF NOT EXISTS tasks_created_idx ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS tasks_usage_idx ON tasks(usage_id);
CREATE INDEX IF NOT EXISTS tasks_status_usage_idx ON tasks(status,usage_id);
CREATE TABLE IF NOT EXISTS task_runs(
 id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,usage_id INTEGER NOT NULL,position INTEGER NOT NULL,model_id TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,max_attempts INTEGER NOT NULL DEFAULT 1,
 available_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,updated_at TEXT NOT NULL,worker_id TEXT,heartbeat_at TEXT,
 duration_seconds REAL,duration_after_vad REAL,processing_seconds REAL,result_json TEXT,error TEXT,
 UNIQUE(task_id,position),UNIQUE(task_id,model_id),FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE SET NULL,FOREIGN KEY(usage_id) REFERENCES usage(id));
CREATE INDEX IF NOT EXISTS task_runs_dispatch_idx ON task_runs(task_id,status,position);
CREATE INDEX IF NOT EXISTS task_runs_model_idx ON task_runs(model_id,status);
CREATE INDEX IF NOT EXISTS task_runs_usage_position_idx ON task_runs(usage_id,position);
CREATE TABLE IF NOT EXISTS uploads(
 upload_id TEXT PRIMARY KEY,api_key_id INTEGER,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,filename TEXT NOT NULL,content_type TEXT,expected_bytes INTEGER NOT NULL,actual_bytes INTEGER,
 sha256 TEXT,object_key TEXT NOT NULL,backend_upload_id TEXT NOT NULL,error TEXT,task_id TEXT);
CREATE INDEX IF NOT EXISTS uploads_owner_idx ON uploads(api_key_id,status,created_at DESC);
CREATE TABLE IF NOT EXISTS task_events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,usage_id INTEGER NOT NULL,created_at TEXT NOT NULL,level TEXT NOT NULL DEFAULT 'info',event_type TEXT NOT NULL DEFAULT 'message',message TEXT NOT NULL,FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE SET NULL,FOREIGN KEY(usage_id) REFERENCES usage(id));
CREATE INDEX IF NOT EXISTS task_events_task_idx ON task_events(task_id,id);
CREATE INDEX IF NOT EXISTS task_events_usage_id_idx ON task_events(usage_id,id);
CREATE TABLE IF NOT EXISTS task_run_events(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id INTEGER NOT NULL,created_at TEXT NOT NULL,level TEXT NOT NULL DEFAULT 'info',event_type TEXT NOT NULL DEFAULT 'message',message TEXT NOT NULL,FOREIGN KEY(run_id) REFERENCES task_runs(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS task_run_events_run_idx ON task_run_events(run_id,id);
CREATE TABLE IF NOT EXISTS api_keys(
 id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,key_prefix TEXT NOT NULL,key_hash TEXT NOT NULL UNIQUE,
 enabled INTEGER NOT NULL DEFAULT 1,scopes_json TEXT NOT NULL DEFAULT '["inference"]',models_json TEXT,
 rate_limit_per_minute INTEGER,expires_at TEXT,created_at TEXT NOT NULL,last_used_at TEXT,revoked_at TEXT);
CREATE INDEX IF NOT EXISTS api_keys_hash_idx ON api_keys(key_hash);
CREATE TABLE IF NOT EXISTS security_rejections(
 id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,reason TEXT NOT NULL,
 client_ip TEXT,origin TEXT,method TEXT NOT NULL,path TEXT NOT NULL,query_string TEXT,
 x_forwarded_for TEXT,x_real_ip TEXT,forwarded TEXT,user_agent TEXT,
 requested_method TEXT,requested_headers TEXT,detail TEXT);
	CREATE INDEX IF NOT EXISTS security_rejections_created_idx ON security_rejections(created_at DESC);
	CREATE INDEX IF NOT EXISTS security_rejections_reason_idx ON security_rejections(reason,created_at DESC);
	CREATE TABLE IF NOT EXISTS request_failures(
	 id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,status_code INTEGER,phase TEXT NOT NULL,
	 reason TEXT NOT NULL,detail TEXT,client_ip TEXT,origin TEXT,method TEXT NOT NULL,path TEXT NOT NULL,
	 query_string TEXT,x_forwarded_for TEXT,x_real_ip TEXT,forwarded TEXT,user_agent TEXT,
	 requested_method TEXT,requested_headers TEXT,task_id TEXT,usage_id INTEGER,dedupe_key TEXT UNIQUE,
	 legacy_security_id INTEGER UNIQUE);
	CREATE INDEX IF NOT EXISTS request_failures_created_idx ON request_failures(created_at DESC);
	CREATE INDEX IF NOT EXISTS request_failures_reason_idx ON request_failures(reason,created_at DESC);
	CREATE INDEX IF NOT EXISTS request_failures_task_idx ON request_failures(task_id,usage_id);
	CREATE INDEX IF NOT EXISTS request_failures_reason_id_idx ON request_failures(reason,id DESC);
	CREATE INDEX IF NOT EXISTS request_failures_phase_id_idx ON request_failures(phase,id DESC);
	CREATE INDEX IF NOT EXISTS request_failures_status_code_id_idx ON request_failures(status_code,id DESC);
CREATE TABLE IF NOT EXISTS custom_models(
 model_id TEXT PRIMARY KEY,kind TEXT NOT NULL,display_name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',
 repository_url TEXT NOT NULL DEFAULT '',architecture TEXT,filename TEXT NOT NULL,download_url TEXT NOT NULL,
 expected_size INTEGER,size_is_estimate INTEGER NOT NULL DEFAULT 0,sha256 TEXT,revision TEXT,license TEXT,
 preparation TEXT,language TEXT,task TEXT,decoding_json TEXT NOT NULL DEFAULT '{}',files_json TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL);
"""
        )
        columns = {x[1] for x in db.execute("PRAGMA table_info(tasks)")}
        if "usage_id" not in columns:
            db.execute("ALTER TABLE tasks ADD COLUMN usage_id INTEGER")
        if "request_fingerprint" not in columns:
            db.execute("ALTER TABLE tasks ADD COLUMN request_fingerprint TEXT")
        if "api_key_id" not in columns:
            db.execute("ALTER TABLE tasks ADD COLUMN api_key_id INTEGER")
        usage_columns = {x[1] for x in db.execute("PRAGMA table_info(usage)")}
        if "execution_log" not in usage_columns:
            db.execute("ALTER TABLE usage ADD COLUMN execution_log TEXT")
        if "result_json" not in usage_columns:
            db.execute("ALTER TABLE usage ADD COLUMN result_json TEXT")
        if "content_type" not in usage_columns:
            db.execute("ALTER TABLE usage ADD COLUMN content_type TEXT")
        custom_model_columns = {x[1] for x in db.execute("PRAGMA table_info(custom_models)")}
        if "files_json" not in custom_model_columns:
            db.execute("ALTER TABLE custom_models ADD COLUMN files_json TEXT")
        if "engine" not in custom_model_columns:
            db.execute("ALTER TABLE custom_models ADD COLUMN engine TEXT")
        if "source_type" not in custom_model_columns:
            db.execute("ALTER TABLE custom_models ADD COLUMN source_type TEXT")
        if "source_json" not in custom_model_columns:
            db.execute("ALTER TABLE custom_models ADD COLUMN source_json TEXT NOT NULL DEFAULT '{}'")
        run_columns = {x[1] for x in db.execute("PRAGMA table_info(task_runs)")}
        if "attempt_started_at" not in run_columns:
            db.execute("ALTER TABLE task_runs ADD COLUMN attempt_started_at TEXT")
        upload_columns = {x[1] for x in db.execute("PRAGMA table_info(uploads)")}
        if "audio_encoding" not in upload_columns:
            db.execute("ALTER TABLE uploads ADD COLUMN audio_encoding TEXT NOT NULL DEFAULT 'identity'")
        if "uncompressed_audio_bytes" not in upload_columns:
            db.execute("ALTER TABLE uploads ADD COLUMN uncompressed_audio_bytes INTEGER")
        db.execute(
            """INSERT OR IGNORE INTO request_failures(
               created_at,status_code,phase,reason,detail,client_ip,origin,method,path,query_string,
               x_forwarded_for,x_real_ip,forwarded,user_agent,requested_method,requested_headers,
               dedupe_key,legacy_security_id)
               SELECT created_at,403,'network_policy',reason,detail,client_ip,origin,method,path,query_string,
               x_forwarded_for,x_real_ip,forwarded,user_agent,requested_method,requested_headers,
               'legacy-security:' || id,id FROM security_rejections"""
        )
        # Backfill one child run for legacy tasks. Keeping model_id on tasks preserves rollback compatibility.
        stamp = now()
        db.execute(
            """INSERT OR IGNORE INTO task_runs(task_id,usage_id,position,model_id,status,attempts,max_attempts,available_at,started_at,finished_at,updated_at,duration_seconds,processing_seconds,result_json,error)
   SELECT task_id,usage_id,0,model_id,CASE status WHEN 'queued' THEN 'pending' WHEN 'running' THEN 'retrying' ELSE status END,attempts,max_attempts,available_at,started_at,finished_at,updated_at,duration_seconds,processing_seconds,result_json,error FROM tasks WHERE usage_id IS NOT NULL"""
        )
        db.execute(
            "INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(1,?)",
            (stamp,),
        )
        db.execute(
            "DELETE FROM settings WHERE key IN ('selected_asr_model','selected_llm_model')"
        )


def execute(sql, args=()):
    with _lock, closing(connect()) as db, db:
        return db.execute(sql, args).lastrowid


def rows(sql, args=()):
    with closing(connect()) as db:
        return [dict(x) for x in db.execute(sql, args).fetchall()]


def row(sql, args=()):
    with closing(connect()) as db:
        x = db.execute(sql, args).fetchone()
        return dict(x) if x else None


def state(mid):
    return row("SELECT * FROM model_state WHERE model_id=?", (mid,)) or {
        "model_id": mid,
        "status": "not_installed",
        "received_bytes": 0,
        "total_bytes": 0,
        "speed_bps": 0,
        "error": None,
    }


def set_state(mid, **values):
    cur = state(mid)
    cur.update(values)
    cur["updated_at"] = now()
    execute(
        "INSERT OR REPLACE INTO model_state(model_id,status,received_bytes,total_bytes,speed_bps,error,installed_at,updated_at,job_id) VALUES(?,?,?,?,?,?,?,?,?)",
        tuple(
            cur.get(k)
            for k in [
                "model_id",
                "status",
                "received_bytes",
                "total_bytes",
                "speed_bps",
                "error",
                "installed_at",
                "updated_at",
                "job_id",
            ]
        ),
    )


def audit(action, mid=None, detail=None):
    execute(
        "INSERT INTO audit(created_at,action,model_id,detail) VALUES(?,?,?,?)",
        (now(), action, mid, detail),
    )
