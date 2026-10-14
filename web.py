"""Local web server: serves the projected face page, pushes face state to it (Server-Sent Events),
streams the annotated camera view, and takes remote-control commands from the page."""

import json
import queue
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from config import ROOT

STATIC = ROOT / "static"
WINDOW_EVENTS = {"creature", "creature_exit", "creature_end", "creature_mouth", "window_calib", "identify",
                 "align_pattern", "align_outline"}


class Hub:
    """Fan-out of events to every open page."""

    def __init__(self):
        self.clients = []
        self.lock = threading.Lock()
        self.recent_logs = []
        self.sticky = {}              # latest alignment per page, replayed to pages that connect later

    def subscribe(self):
        q = queue.Queue(maxsize=200)
        with self.lock:
            self.clients.append(q)
            backlog = list(self.sticky.values()) + list(self.recent_logs)
        for ev in backlog:
            q.put_nowait(ev)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)

    def publish(self, event):
        if event.get("t") == "log":
            with self.lock:
                self.recent_logs = (self.recent_logs + [event])[-40:]
        elif event.get("t") in ("calib", "window_calib", "show", "face_warp"):   # sticky: new pages get the latest alignment
            with self.lock:
                self.sticky[(event["t"], event.get("screen"))] = event
        with self.lock:
            clients = list(self.clients)
        for q in clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass


def serve(cfg, hub, app):
    """app provides: command(name, data) -> dict, status() -> dict, debug_jpeg() -> bytes|None."""

    class Handler(SimpleHTTPRequestHandler):
        # Windows looks MIME types up in the registry, which often says text/plain for .js; browsers then
        # refuse to run the pages' modules. Pin the ones the pages use.
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript",
                          ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html",
                          ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".m4v": "video/mp4"}

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC), **kwargs)

        def log_message(self, fmt, *args):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/events"):
                return self._events()
            if self.path.startswith("/video.mjpg"):
                return self._mjpeg()
            if self.path.startswith("/api/status"):
                return self._json(200, app.status())
            return super().do_GET()

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > (12_000_000 if self.path.startswith("/api/align_photo") else 10000):
                return self._json(413, {"error": "too large"})
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "bad json"})
            if self.path.startswith("/api/"):
                return self._json(200, app.command(self.path[5:], data))
            return self._json(404, {"error": "not found"})

        def _events(self):
            # A window page (events?w=garage) only gets its own creature and alignment events: the projectors
            # are on Wi-Fi, so skip the face's many updates per second.
            screen = (parse_qs(urlparse(self.path).query).get("w") or [None])[0]
            wanted = (lambda ev: ev.get("t") in WINDOW_EVENTS and ev.get("screen") in (None, screen)) if screen else None
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            q = hub.subscribe()
            last = time.time()
            try:
                while True:
                    try:
                        ev = q.get(timeout=10)
                        if wanted and not wanted(ev):
                            if time.time() - last < 10:
                                continue
                            raise queue.Empty
                        self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last = time.time()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hub.unsubscribe(q)

        def _mjpeg(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    jpg = app.debug_jpeg()
                    if jpg:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                         + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                        self.wfile.flush()
                    time.sleep(0.15)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    server = ThreadingHTTPServer((cfg["host"], int(cfg["port"])), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="web").start()
    return server
