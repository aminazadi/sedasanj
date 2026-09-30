import json
import time
from urllib.parse import quote, urlsplit, urlunsplit

try:
    import requests
except ImportError:
    requests = None

from .storage import execute, now, row

SETTING_KEY = "download_proxy"
STATUS_KEY = "download_proxy_status"
TEST_URL = "https://huggingface.co/robots.txt"


def _saved():
    item = row("SELECT value FROM settings WHERE key=?", (SETTING_KEY,))
    if not item:
        return {"enabled": False, "host": "", "port": 1080, "username": "", "password": ""}
    try:
        return {"enabled": False, "host": "", "port": 1080, "username": "", "password": "", **json.loads(item["value"])}
    except (TypeError, ValueError):
        return {"enabled": False, "host": "", "port": 1080, "username": "", "password": ""}


def _uri(config):
    if config.get("uri"):
        return config["uri"]
    auth = ""
    if config.get("username"):
        auth = quote(config["username"], safe="")
        if config.get("password"):
            auth += ":" + quote(config["password"], safe="")
        auth += "@"
    host = config.get("host", "")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"socks5h://{auth}{host}:{config.get('port', 1080)}" if host else ""


def _safe_uri(uri):
    if not uri:
        return ""
    parsed = urlsplit(uri)
    auth = quote(parsed.username, safe="") if parsed.username else ""
    if parsed.password is not None:
        auth += ":••••"
    if auth:
        auth += "@"
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"{auth}{host}{port}", parsed.path, parsed.query, parsed.fragment))


def public_config():
    config = _saved()
    uri = _uri(config)
    parsed = urlsplit(uri) if uri else None
    status = row("SELECT value FROM settings WHERE key=?", (STATUS_KEY,))
    try:
        last_test = json.loads(status["value"]) if status else None
    except (TypeError, ValueError):
        last_test = None
    return {
        "enabled": bool(config["enabled"]),
        "host": config["host"],
        "port": config["port"],
        "username": config["username"],
        "has_password": bool(config["password"]),
        "scheme": parsed.scheme if parsed else "",
        "uri": _safe_uri(uri),
        "has_password": urlsplit(uri).password is not None if uri else False,
        "last_test": last_test,
    }


def save_config(enabled, uri):
    old_uri = _uri(_saved())
    if old_uri and uri == _safe_uri(old_uri):
        uri = old_uri
    config = {"enabled": bool(enabled), "uri": uri.strip()}
    execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (SETTING_KEY, json.dumps(config)))
    execute("DELETE FROM settings WHERE key=?", (STATUS_KEY,))
    return public_config()


def _remember(result):
    safe = {key: value for key, value in result.items() if key != "last_test"}
    execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (STATUS_KEY, json.dumps(safe)))
    return safe


def proxy_url():
    config = _saved()
    if not config["enabled"]:
        return None
    return _uri(config)


def download_session():
    if requests is None:
        raise RuntimeError("requests is required for downloads")
    session = requests.Session()
    session.trust_env = False
    url = proxy_url()
    if url:
        session.proxies.update({"http": url, "https": url})
    return session


def test_connection():
    config = public_config()
    result = {**config, "checked_at": now(), "target": TEST_URL, "remote_dns": True}
    if not config["enabled"]:
        return _remember({**result, "state": "disabled", "message": "پراکسی غیرفعال است.", "latency_ms": None, "http_status": None})
    if not config["uri"]:
        return _remember({**result, "state": "error", "message": "URI پراکسی وارد نشده است.", "latency_ms": None, "http_status": None})
    if requests is None:
        return _remember({**result, "state": "error", "message": "requests is required for proxy testing.", "latency_ms": None, "http_status": None})
    started = time.monotonic()
    try:
        with download_session().get(TEST_URL, timeout=(8, 15), stream=True, allow_redirects=True) as response:
            elapsed = round((time.monotonic() - started) * 1000)
            if response.status_code >= 400:
                return _remember({**result, "state": "error", "message": f"Hugging Face پاسخ HTTP {response.status_code} داد.", "latency_ms": elapsed, "http_status": response.status_code})
            return _remember({**result, "state": "connected", "message": "اتصال SOCKS5H به Hugging Face برقرار است.", "latency_ms": elapsed, "http_status": response.status_code, "final_url": response.url})
    except requests.RequestException as exc:
        message = str(exc)
        url = proxy_url()
        if url:
            message = message.replace(url, _safe_uri(url))
        return _remember({**result, "state": "error", "message": message, "latency_ms": round((time.monotonic() - started) * 1000), "http_status": None})
