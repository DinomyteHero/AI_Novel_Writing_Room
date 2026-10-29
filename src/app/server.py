"""The Writers Room app: a small local web server and the page it serves.

Run it with ``python scripts/app.py``. It listens on this computer only and
opens the app in the browser. Every API call must carry the token printed into
the page, so other websites can't drive it.
"""

from __future__ import annotations

import errno
import json
import logging
import mimetypes
import secrets
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.app.api import App
from src.studio.llm import provider_error
from src.studio.project import StudioError

STATIC = Path(__file__).resolve().parent / "static"
logger = logging.getLogger(__name__)


def routes(app: App) -> dict:
    """(method, path) -> handler taking the request's parameters."""
    return {
        ("GET", "/api/state"): lambda p: {
            "projects": app.projects(), "recents": app.recents(),
            "providers": [x for x in app.settings()["providers"] if x["connected"]],
        },
        ("GET", "/api/project"): lambda p: app.project(p["project"], p.get("book")),
        ("GET", "/api/file"): lambda p: app.read_file(p["project"], p["path"]),
        ("GET", "/api/chat"): lambda p: app.load_chat(p["project"], p["chat"]),
        ("GET", "/api/settings"): lambda p: app.settings(),
        ("GET", "/api/build"): lambda p: app.build_status(p["project"], p.get("book")),
        ("GET", "/api/estimate"): lambda p: app.estimate(p["project"], p.get("book"), p["which"]),
        ("POST", "/api/projects"): lambda p: app.create_project(p.get("idea", ""), p.get("kind", "book"), p.get("defer", False)),
        ("POST", "/api/chats"): lambda p: app.new_chat(
            p["project"], p.get("backend") or "", p.get("model") or "", p.get("effort")
        ),
        ("POST", "/api/send"): lambda p: app.send(
            p["project"], p["chat"], p.get("text", ""), p.get("attachments"), p.get("book"),
            selection=p.get("selection"), explore=p.get("explore", False),
            edit_mode=p.get("edit_mode", "auto"),
        ),
        ("POST", "/api/chat/stop"): lambda p: app.stop_turn(p["project"], p["chat"]),
        ("POST", "/api/chat/model"): lambda p: app.set_chat_model(
            p["project"], p["chat"], p["backend"], p["model"]
        ),
        ("POST", "/api/chat/effort"): lambda p: app.set_chat_effort(
            p["project"], p["chat"], p.get("effort") or ""
        ),
        ("POST", "/api/chat/attachment/remove"): lambda p: app.forget_attachment(p["project"], p["chat"], p["path"]),
        ("POST", "/api/undo"): lambda p: app.undo(p["project"], p["chat"], p["item"]),
        ("POST", "/api/proposal"): lambda p: app.decide_proposal(
            p["project"], p["chat"], p["item"], p["decision"]
        ),
        ("POST", "/api/build"): lambda p: app.build(
            p["project"], p.get("book"), p["which"], p.get("chat"), p.get("item")
        ),
        ("POST", "/api/build/decline"): lambda p: app.decline_build(p["project"], p["chat"], p["item"]),
        ("POST", "/api/build/stop"): lambda p: app.stop_build(p["project"], p.get("book")),
        ("POST", "/api/file"): lambda p: app.save_file(p["project"], p["path"], p["text"], p.get("version")),
        ("POST", "/api/reference"): lambda p: app.add_reference(
            p["project"], p.get("scope", "book"), p.get("book"), p["name"], p["data"]
        ),
        ("POST", "/api/reference/remove"): lambda p: app.remove_reference(p["project"], p["path"], p.get("book")),
        ("POST", "/api/attachment"): lambda p: app.attachment(p["name"], p["data"]),
        ("POST", "/api/settings/effort"): lambda p: app.set_effort(p["role"], p.get("effort") or ""),
        ("POST", "/api/review/call"): lambda p: app.review_call(p["project"], p["path"], p["number"], p["call"]),
        ("POST", "/api/export"): lambda p: app.export(p["project"], p.get("book")),
        ("POST", "/api/settings/key"): lambda p: app.set_key(p["backend"], p.get("value", "")),
        ("POST", "/api/settings/check"): lambda p: app.check(p["backend"]),
        ("POST", "/api/settings/role"): lambda p: app.set_role(p["role"], p["backend"], p["model"]),
        ("POST", "/api/settings/automatic"): lambda p: app.use_automatic(),
        ("POST", "/api/models/refresh"): lambda p: app.refresh_models(),
        ("POST", "/api/settings/library"): lambda p: app.set_library(p.get("path", "")),
        ("POST", "/api/settings/press"): lambda p: app.set_press(
            p.get("revision_rounds"), p.get("default_chapter_words")
        ),
    }


def make_handler(app: App, token: str):
    table = routes(app)
    local_hosts = ("127.0.0.1", "localhost")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet by default
            logger.debug(fmt, *args)

        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

        def _static(self, path: str) -> None:
            name = "index.html" if path in ("/", "/index.html") else path.removeprefix("/static/")
            target = (STATIC / name).resolve()
            if STATIC.resolve() not in target.parents or not target.is_file():
                self._send(404, b"Not found", "text/plain")
                return
            body = target.read_bytes()
            if target.name == "index.html":
                body = body.replace(b"__WRITERS_ROOM_TOKEN__", token.encode())
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(200, body, kind + ("; charset=utf-8" if kind.startswith("text/") or kind.endswith("javascript") else ""))

        def _api(self, method: str) -> None:
            url = urlparse(self.path)
            if self.headers.get("X-Writers-Room-Token") != token:
                self._json(403, {"error": "Reload the page: the app was restarted."})
                return
            handler = table.get((method, url.path))
            streaming = method == "POST" and url.path == "/api/send/stream"
            if handler is None and not streaming:
                self._json(404, {"error": "Unknown request."})
                return
            params = {k: v[0] for k, v in parse_qs(url.query).items()}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    params.update(json.loads(self.rfile.read(length) or b"{}"))
            try:
                if streaming:
                    return self._stream_turn(params)
                self._json(200, handler(params))
            except StudioError as exc:
                self._json(400, {"error": str(exc)})
            except KeyError as exc:
                self._json(400, {"error": f"Missing {exc} in the request."})
            except Exception as exc:  # shown to the writer, never a traceback
                explained = provider_error(exc)
                if explained:
                    self._json(502, {"error": f"{explained} Nothing half-done was saved."})
                    return
                logger.exception("Request failed")
                self._json(500, {"error": f"Something went wrong: {exc}"})

        def _stream_turn(self, params: dict) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            disconnected = False

            def emit(event):
                nonlocal disconnected
                if disconnected:
                    return
                try:
                    self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                    self.wfile.flush()
                except OSError:
                    disconnected = True
                    app.stop_turn(params.get("project", ""), params.get("chat", ""))

            try:
                app.send(params["project"], params["chat"], params.get("text", ""),
                         params.get("attachments"), params.get("book"), on_event=emit,
                         selection=params.get("selection"), explore=params.get("explore", False),
                         edit_mode=params.get("edit_mode", "auto"))
            except (StudioError, KeyError) as exc:
                emit({"kind": "error", "text": str(exc)})
            except Exception:
                logger.exception("Could not start a planning turn")
                emit({"kind": "error", "text": "Couldn't start this turn. Reopen the chat to check saved changes before trying again."})

        def _local(self) -> bool:
            # Refuse requests addressed to any other name, so a web page can't
            # reach the app by pointing its own domain at this computer.
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if host in local_hosts:
                return True
            self._send(403, b"Forbidden", "text/plain")
            return False

        def do_GET(self):
            if not self._local():
                return
            if self.path.startswith("/api/"):
                self._api("GET")
            else:
                self._static(urlparse(self.path).path)

        def do_POST(self):
            if self._local():
                self._api("POST")

    return Handler


class _Server(ThreadingHTTPServer):
    def server_bind(self):
        # On Windows, SO_REUSEADDR lets a second copy bind a port that's in use
        # and quietly answer some of its requests; claim the port outright.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve(app: App, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    token = secrets.token_urlsafe(24)
    try:
        server = _Server((host, port), make_handler(app, token))
    except OSError as exc:
        if exc.errno not in (errno.EADDRINUSE, errno.EACCES):
            raise
        raise SystemExit(
            f"Port {port} is already in use. The Writers Room may already be running: open "
            f"http://{host}:{port}/ or close that window first. To run another copy, add --port {port + 1}."
        ) from exc
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"Writers Room is running at {url}\nKeep this window open while you write; press Ctrl+C to quit.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nClosed. Your books are in", app.library.root)
    finally:
        server.server_close()
