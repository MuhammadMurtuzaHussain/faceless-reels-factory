"""A tiny stand-in for the Telegram Bot API, for testing the n8n workflows offline.

    python tests/tools/mock_telegram.py --port 8899 --log /tmp/tg.jsonl

- POST /_say {"text": "/status", "chat_id": 42} queues an incoming message
- GET  /_log returns every bot call recorded so far (sendMessage/sendPhoto/...)
- /bot<token>/getUpdates honours `offset` (confirms) like the real API
"""
from __future__ import annotations

import argparse
import json
import threading
from email.parser import BytesParser
from email.policy import default as email_default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOCK = threading.Lock()
STATE = {"updates": [], "next_id": 1000, "calls": []}


class H(BaseHTTPRequestHandler):
    log_path = None

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, method, fields):
        with LOCK:
            STATE["calls"].append({"method": method, **fields})
            if self.log_path:
                with open(self.log_path, "a") as f:
                    f.write(json.dumps({"method": method, **fields}) + "\n")

    def _params(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        ctype = self.headers.get("Content-Type", "")
        files = {}
        if ctype.startswith("application/json") and raw:
            q.update(json.loads(raw))
        elif ctype.startswith("multipart/form-data"):
            msg = BytesParser(policy=email_default).parsebytes(
                b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw)
            for part in msg.iter_parts():
                name = part.get_param("name", header="content-disposition")
                payload = part.get_payload(decode=True) or b""
                if part.get_filename():
                    files[name] = {"filename": part.get_filename(), "bytes": len(payload),
                                   "content_type": part.get_content_type()}
                else:
                    q[name] = payload.decode("utf-8", "replace")
        elif raw:
            q.update({k: v[0] for k, v in parse_qs(raw.decode()).items()})
        return u.path, q, files

    def do_GET(self):
        self.handle_any()

    def do_POST(self):
        self.handle_any()

    def handle_any(self):
        path, q, files = self._params()
        if path == "/_say":
            with LOCK:
                STATE["next_id"] += 1
                STATE["updates"].append({"update_id": STATE["next_id"], "message": {
                    "message_id": STATE["next_id"], "chat": {"id": int(q.get("chat_id", 42))}, "text": q.get("text", "")}})
            return self._json({"ok": True})
        if path == "/_log":
            return self._json(STATE["calls"])
        parts = path.strip("/").split("/")
        if len(parts) != 2 or not parts[0].startswith("bot"):
            return self._json({"ok": False, "description": "Not Found"}, 404)
        method = parts[1]
        if method == "getUpdates":
            off = int(q.get("offset", 0) or 0)
            with LOCK:
                if off:
                    STATE["updates"] = [u for u in STATE["updates"] if u["update_id"] >= off]
                res = STATE["updates"][: int(q.get("limit", 100))]
            return self._json({"ok": True, "result": res})
        self._record(method, {"params": {k: v for k, v in q.items() if k != "chat_id"},
                              "chat_id": q.get("chat_id"), "files": files})
        return self._json({"ok": True, "result": {"message_id": len(STATE["calls"])}})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--log")
    a = ap.parse_args()
    H.log_path = a.log
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
