"""Minimal SedaSanj meetings API stand-in for emulator tests.

Implements the contract the app uses (pair, validate, text sessions, transcript,
status, finish) with in-memory state. Audio chunks are accepted and kept only
for playback, like the real server does for text meetings. Run:
    python3 test/tools/fake_sedasanj.py [port]
The Android emulator reaches it at http://10.0.2.2:<port>.
"""
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "sk_test_fake_token_0001"
MEETINGS = {}
FINISHED_AT = {}


def parse_multipart(body, boundary):
    fields, files = {}, {}
    for part in body.split(b"--" + boundary)[1:-1]:
        head, _, data = part.lstrip(b"\r\n").partition(b"\r\n\r\n")
        data = data[:-2] if data.endswith(b"\r\n") else data
        name = re.search(rb'name="([^"]+)"', head).group(1).decode()
        if b"filename=" in head:
            files[name] = data
        else:
            fields[name] = data.decode()
    return fields, files


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload=None):
        body = json.dumps(payload if payload is not None else {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._send(401, {"error": {"code": "unauthorized", "message": "bad token"}})
            return False
        return True

    def _body(self):
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def log_message(self, fmt, *args):
        print("[fake]", self.command, self.path, args[1] if len(args) > 1 else "")

    def do_POST(self):
        if self.path == "/v1/meetings/devices/pair":
            data = json.loads(self._body())
            if data.get("pairing_code") != "ABCD2345":
                return self._send(400, {"error": {"code": "meeting_pairing_invalid", "message": "x"}})
            return self._send(201, {
                "token": TOKEN, "token_prefix": "sk_test_fake",
                "user": {"display_name": "کاربر آزمایشی"}, "tenant": {"name": "سازمان آزمایشی"},
            })
        if not self._authed():
            return
        if self.path == "/v1/meetings/sessions":
            data = json.loads(self._body())
            m = MEETINGS.setdefault(data["client_meeting_id"], {"id": "mtg-" + data["client_meeting_id"][:8], "chunks": {}, "segments": None, "status": "receiving"})
            return self._send(200, {"meeting_id": m["id"], "status": m["status"], "received_seqs": [], "chunk_max_bytes": 5_000_000, "input_kind": data.get("input_kind", "audio"), "transcript_received": m["segments"] is not None})
        m = re.match(r"/v1/meetings/([^/]+)/finish", self.path)
        if m:
            data = json.loads(self._body())
            meeting = next(v for v in MEETINGS.values() if v["id"] == m.group(1))
            if not meeting["segments"]:
                return self._send(409, {"error": {"code": "meeting_transcript_missing", "message": "x"}})
            missing = [s for s in range(data["total_chunks"]) if s not in meeting["chunks"]]
            if missing:
                return self._send(409, {"error": {"code": "meeting_incomplete_chunks", "message": "x", "missing_seqs": missing}})
            meeting["status"] = "processing"
            FINISHED_AT[meeting["id"]] = time.time()
            return self._send(202, {"meeting_id": meeting["id"], "status": "processing"})
        self._send(404, {})

    def do_PUT(self):
        if not self._authed():
            return
        c = re.match(r"/v1/meetings/([^/]+)/chunks/(\d+)", self.path)
        if c:
            # Audio is stored for playback only; nothing is transcribed.
            meeting = next(v for v in MEETINGS.values() if v["id"] == c.group(1))
            meeting["chunks"][int(c.group(2))] = len(self._body())
            return self._send(200, {"seq": int(c.group(2)), "status": "received"})
        m = re.match(r"/v1/meetings/([^/]+)/transcript", self.path)
        if not m:
            return self._send(404, {})
        data = json.loads(self._body())
        meeting = next(v for v in MEETINGS.values() if v["id"] == m.group(1))
        meeting["segments"] = data["segments"]
        self._send(200, {"segments": len(data["segments"]), "sha256": "x", "replay": False})

    def do_GET(self):
        if self.path == "/v1/meetings/config/validate":
            if not self._authed():
                return
            return self._send(200, {"ok": True, "user": {"display_name": "کاربر آزمایشی"}, "tenant": {"name": "سازمان آزمایشی"}})
        m = re.match(r"/v1/meetings/([^/]+)/status", self.path)
        if m and self._authed():
            meeting = next(v for v in MEETINGS.values() if v["id"] == m.group(1))
            if meeting["status"] == "processing" and time.time() - FINISHED_AT[meeting["id"]] > 15:
                meeting["status"] = "complete"
            return self._send(200, {"status": meeting["status"], "received_seqs": [], "processed_seqs": [], "progress_pct": 50, "progress_detail": None, "error_code": None})
        self._send(404, {})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
