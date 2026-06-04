"""Local web server for visual output.

The board is headless, so the captured frame plus each demo's payload are pushed
to a page you open on your phone or laptop over USB networking.

Implemented with the Python stdlib only (http.server + Server-Sent Events), so
there are no dependencies to install on the board. Call broadcast(...) and any
connected browser updates live.

This module is the SAME on the board and on a laptop (it's just a web server),
so it has no MOCK branch.
"""

import json
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config

_WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "hello_world", "web")

# Subscribers (one queue per open browser tab) for SSE fan-out.
_subscribers = set()
_subscribers_lock = threading.Lock()
_latest = {"photo": None, "text": "", "mood": "#111111", "title": ""}
_photo_path = {"path": None}
_action_handler = {"fn": None}


def set_action_handler(fn):
    """Register a callback fn(params: dict) invoked for GET /action?key=val...
    Lets a demo expose live controls from its web page (e.g. LED/buzzer buttons)."""
    _action_handler["fn"] = fn


def broadcast(payload: dict):
    """Push an arbitrary JSON payload to every connected browser over SSE.

    Each demo defines its own message shape (its index.html interprets it). The
    last payload is replayed to new tabs so they aren't blank. This is the
    generic primitive; publish() below is the P3 (photo+poem) convenience."""
    global _latest
    _latest = payload
    data = json.dumps(payload)
    with _subscribers_lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(data)
            except Exception:
                dead.append(q)
        for q in dead:
            _subscribers.discard(q)


def set_photo(path):
    """Register the JPEG served at /photo.jpg (without sending a payload), so any
    demo can show a captured frame alongside its own broadcast()."""
    _photo_path["path"] = path


def publish(text, photo_path=None, mood="#111111", title=""):
    """Push a P3-style result (poem + captured photo) to every browser."""
    payload = {"text": text, "mood": mood, "title": title, "photo": None}
    if photo_path:
        set_photo(photo_path)
        payload["photo"] = "/photo.jpg"
    broadcast(payload)


def serve(web_dir=None, host=None, port=None):
    """Start the server in a background thread. Returns the server instance."""
    global _WEB_DIR
    if web_dir:
        _WEB_DIR = web_dir
    host = host or config.WEB_HOST
    port = port or config.WEB_PORT
    httpd = ThreadingHTTPServer((host, port), _Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    print(f"web up at http://{host}:{port} (open on your phone/laptop)")
    return httpd


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # quiet

    def do_GET(self):
        path = self.path.split("?", 1)[0]   # ignore cache-busting query (?t=…)
        if path == "/" or path == "/index.html":
            self._send_file(os.path.join(_WEB_DIR, "index.html"), "text/html")
        elif path == "/photo.jpg":
            p = _photo_path["path"]
            if p and os.path.exists(p):
                self._send_file(p, "image/jpeg")
            else:
                self.send_error(404)
        elif path == "/events":
            self._stream_events()
        elif path == "/action":
            self._do_action()
        else:
            self.send_error(404)

    def _do_action(self):
        from urllib.parse import parse_qs, urlparse
        params = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        fn = _action_handler["fn"]
        ok = True
        if fn:
            try:
                fn(params)
            except Exception:
                ok = False
        body = b'{"ok": true}' if ok else b'{"ok": false}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = queue.Queue()
        with _subscribers_lock:
            _subscribers.add(q)
        # Send current state immediately so a fresh tab isn't blank.
        try:
            self._sse(json.dumps(_latest))
            while True:
                payload = q.get()
                self._sse(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _subscribers_lock:
                _subscribers.discard(q)

    def _sse(self, data):
        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()
