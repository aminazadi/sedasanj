"""Safe, append-only persistence for unsuccessful API and processing outcomes."""

import logging
from urllib.parse import unquote_plus

from .storage import execute, now


logger = logging.getLogger("asr_service.failures")


def _safe_query_string(raw):
    """Redact common credential fields while preserving useful query context."""

    sensitive_fragments = ("api_key", "apikey", "authorization", "password", "secret", "token")
    parts = []
    for part in raw.decode("utf-8", errors="replace").split("&"):
        key, separator, value = part.partition("=")
        normalized = unquote_plus(key).strip().lower()
        if separator and any(fragment in normalized for fragment in sensitive_fragments):
            value = "[REDACTED]"
        parts.append(key + (separator + value if separator else ""))
    return "&".join(parts)[:4000]


def request_metadata(scope):
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1", errors="replace")
        for key, value in scope.get("headers", [])
    }
    query = scope.get("query_string", b"")
    client = (scope.get("client") or ("", 0))[0]
    return {
        "client_ip": client,
        "origin": headers.get("origin"),
        "method": scope.get("method", ""),
        "path": scope.get("path", ""),
        "query_string": _safe_query_string(query),
        "x_forwarded_for": headers.get("x-forwarded-for"),
        "x_real_ip": headers.get("x-real-ip"),
        "forwarded": headers.get("forwarded"),
        "user_agent": headers.get("user-agent"),
        "requested_method": headers.get("access-control-request-method"),
        "requested_headers": headers.get("access-control-request-headers"),
    }


def record_failure(
    *,
    status_code=None,
    phase,
    reason,
    detail=None,
    scope=None,
    task_id=None,
    usage_id=None,
    dedupe_key=None,
    **metadata,
):
    """Persist safe request metadata without request bodies or credentials."""

    values = request_metadata(scope) if scope is not None else {}
    values.update({key: value for key, value in metadata.items() if value is not None})
    values.setdefault("method", "TASK" if task_id else "")
    values.setdefault("path", f"/v1/tasks/{task_id}" if task_id else "")
    try:
        return execute(
            """INSERT OR IGNORE INTO request_failures(
               created_at,status_code,phase,reason,detail,client_ip,origin,method,path,query_string,
               x_forwarded_for,x_real_ip,forwarded,user_agent,requested_method,requested_headers,
               task_id,usage_id,dedupe_key)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now(),
                status_code,
                str(phase)[:80],
                str(reason)[:160],
                str(detail)[:4000] if detail else None,
                values.get("client_ip"),
                values.get("origin"),
                values.get("method", ""),
                values.get("path", ""),
                values.get("query_string"),
                values.get("x_forwarded_for"),
                values.get("x_real_ip"),
                values.get("forwarded"),
                values.get("user_agent"),
                values.get("requested_method"),
                values.get("requested_headers"),
                task_id,
                usage_id,
                dedupe_key,
            ),
        )
    except Exception:
        logger.exception("Failed to persist unsuccessful request")
        return None
