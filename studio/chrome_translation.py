"""Authenticated loopback bridge to an explicitly opened Chrome helper page."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from threading import Event, Lock, Thread
import time
from urllib.parse import urlsplit
from uuid import uuid4

from .translation_bridge import PAGE


class ChromeConnectionError(RuntimeError):
    pass


def chrome_executable():
    candidates = []
    if sys.platform == 'darwin':
        for base in (Path('/Applications'), Path.home() / 'Applications'):
            candidates.append(base / 'Google Chrome.app/Contents/MacOS/Google Chrome')
    if os.name == "nt":
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
                                        0, winreg.KEY_READ | view) as key:
                        candidates.append(Path(winreg.QueryValueEx(key, "")[0].strip('"')))
                except OSError:
                    pass
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("PROGRAMFILES"),
                 os.environ.get("PROGRAMFILES(X86)")):
        if base:
            candidates.append(Path(base) / "Google/Chrome/Application/chrome.exe")
    return next((path for path in candidates if path.is_file()), None)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(5)
        return sock, address


class ChromeTranslator:
    name = "Chrome 내장 번역"

    def __init__(self):
        self.lock = Lock()
        self.closed = Event()
        self.token = secrets.token_urlsafe(32)
        self.client = ""
        self.last_seen = 0.0
        self.last_opened = 0.0
        self.state = "waiting"
        self.message = "Chrome 번역 도우미에서 번역 준비를 눌러 주세요."
        self.pending = None
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            # Local document content and credentials must never enter HTTP logs.
            def log_message(self, *args):
                pass

            def reply(self, status, value, content_type="application/json; charset=utf-8"):
                data = value.encode("utf-8") if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (OSError, TimeoutError):
                    pass

            def valid_host(self):
                return self.headers.get("Host") == bridge.host

            def do_GET(self):
                if not self.valid_host():
                    self.reply(403, {"error": "허용되지 않는 연결입니다."})
                    return
                path = urlsplit(self.path).path
                if path == "/":
                    self.reply(200, PAGE, "text/html; charset=utf-8")
                elif path == "/bridge.js":
                    from .translation_bridge import SCRIPT
                    self.reply(200, SCRIPT, "text/javascript; charset=utf-8")
                else:
                    self.reply(404, {})

            def do_POST(self):
                if (not self.valid_host() or self.headers.get("Origin") != bridge.origin
                        or not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + bridge.token)):
                    self.reply(403, {"error": "앱에서 Chrome 번역 연결을 다시 열어 주세요."})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 512000 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                        self.reply(413, {"error": "요청 크기 또는 형식이 올바르지 않습니다."})
                        return
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise ValueError()
                    result = bridge.handle(urlsplit(self.path).path, data, self.headers.get("Authorization", ""))
                    self.reply(200, result)
                except (ValueError, UnicodeError, KeyError, TypeError):
                    self.reply(400, {"error": "올바르지 않은 번역 요청입니다."})
                except OSError:
                    self.close_connection = True

        self.server = _Server(("127.0.0.1", 0), Handler)
        self.host = "127.0.0.1:" + str(self.server.server_address[1])
        self.origin = "http://" + self.host
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": .2}, daemon=True)
        self.thread.start()

    def handle(self, path, data, authorization):
        client = data.get("client", "")
        if not isinstance(client, str) or not 8 <= len(client) <= 80:
            raise ValueError()
        with self.lock:
            # Reconnecting can rotate the token while an old request waits on
            # this lock. That old tab must not claim the new connection.
            if not secrets.compare_digest(authorization, "Bearer " + self.token):
                return {"error": "새 Chrome 연결이 열렸습니다. 새 번역 도우미를 사용해 주세요."}
            now = time.monotonic()
            if self.closed.is_set():
                return {"error": "앱의 번역 연결이 종료되었습니다."}
            if self.client and self.client != client and now - self.last_seen < 35:
                return {"error": "다른 번역 도우미 창이 연결되어 있습니다. 그 창을 사용해 주세요."}
            if self.client != client:
                if self.pending and self.pending["dispatched"]:
                    self.pending["error"] = "Chrome 연결이 바뀌었습니다. 미처리 문장을 다시 번역해 주세요."
                    self.pending["done"].set()
                self.client = client
            self.last_seen = now
            state = data.get("state")
            if state in ("waiting", "downloading", "ready", "busy", "error", "unsupported"):
                self.state = state
                message = data.get("message", "")
                self.message = message[:300] if isinstance(message, str) else ""
            if path == "/api/poll":
                if self.state == "ready" and self.pending and not self.pending["dispatched"]:
                    self.pending["dispatched"] = True
                    return {"job": self.pending["request"]}
                return {}
            if path == "/api/heartbeat":
                job_id = data.get("job")
                return {"cancel": bool(job_id and (not self.pending or self.pending["request"]["id"] != job_id))}
            if path == "/api/result":
                pending = self.pending
                if not pending or pending["request"]["id"] != data.get("id") or pending["done"].is_set():
                    return {"ignored": True}
                if data.get("source_hash") != pending["request"]["source_hash"]:
                    raise ValueError()
                target, error = data.get("target", ""), data.get("error", "")
                if not isinstance(target, str) or not isinstance(error, str) or len(target) > 120000:
                    raise ValueError()
                if not target.strip() and not error:
                    error = "Chrome가 빈 번역문을 반환했습니다."
                pending["target"], pending["error"] = target.strip(), error[:300]
                pending["done"].set()
                return {"accepted": True}
            raise ValueError()

    def open(self, force=False):
        if self.closed.is_set():
            raise ChromeConnectionError("Chrome 번역 연결이 종료되었습니다.")
        with self.lock:
            now = time.monotonic()
            if not force and ((self.client and now - self.last_seen < 35) or now - self.last_opened < 15):
                return
            executable = chrome_executable()
            if executable is None:
                raise ChromeConnectionError("Chrome를 찾지 못했습니다. Chrome를 설치하거나 번역 설정에서 오프라인 엔진을 선택해 주세요.")
            if force and self.pending:
                raise ChromeConnectionError("진행 중인 번역을 중단한 뒤 다시 연결해 주세요.")
            # A new token prevents abandoned helper tabs from consuming jobs.
            self.token = secrets.token_urlsafe(32)
            self.client = ""
            self.state = "waiting"
            self.last_seen = 0
            self.message = "Chrome 번역 도우미에서 번역 준비를 눌러 주세요."
            url = self.origin + "/#" + self.token
            try:
                subprocess.Popen([str(executable), "--new-window", "--app=" + url],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == 'nt' else 0)
            except OSError as exc:
                raise ChromeConnectionError("Chrome를 열지 못했습니다. 설치 상태를 확인해 주세요.") from exc
            self.last_opened = now

    def translate(self, text, cancelled, progress, identity):
        if cancelled.is_set():
            return ""
        self.open()
        deadline = time.monotonic() + 600
        last_message = ""
        while not cancelled.is_set():
            with self.lock:
                state, message, seen = self.state, self.message, self.last_seen
            if self.closed.is_set():
                raise ChromeConnectionError("Chrome 번역 연결이 종료되었습니다.")
            if state in ("error", "unsupported"):
                raise ChromeConnectionError(message or "Chrome 번역을 준비하지 못했습니다.")
            if state == "ready" and time.monotonic() - seen < 35:
                break
            if seen and time.monotonic() - seen > 35:
                raise ChromeConnectionError("Chrome 도우미 연결이 끊겼습니다. 번역 연결을 다시 열고 미처리 항목을 번역해 주세요.")
            if time.monotonic() > deadline:
                raise ChromeConnectionError("Chrome 번역 준비 대기 시간이 지났습니다. 보조 창에서 준비 후 다시 번역해 주세요.")
            if message != last_message:
                progress(message or "Chrome 번역 준비를 기다립니다…")
                last_message = message
            cancelled.wait(.2)
        if cancelled.is_set():
            return ""
        pending = {"request": {**identity, "id": uuid4().hex, "text": text},
                   "done": Event(), "dispatched": False, "target": "", "error": ""}
        with self.lock:
            if self.pending is not None:
                raise ChromeConnectionError("다른 번역이 처리 중입니다.")
            self.pending = pending
        progress("Chrome에서 문단을 번역하고 있습니다…")
        deadline = time.monotonic() + 180
        try:
            while not pending["done"].wait(.2):
                if cancelled.is_set():
                    return ""
                if self.closed.is_set():
                    raise ChromeConnectionError("Chrome 번역 연결이 종료되었습니다.")
                with self.lock:
                    seen = self.last_seen
                if time.monotonic() - seen > 35 or time.monotonic() > deadline:
                    raise ChromeConnectionError("Chrome 번역 응답이 중단되었습니다. 완료된 결과는 유지됩니다. 다시 연결해 주세요.")
            if cancelled.is_set():
                return ""
            if pending["error"]:
                raise ChromeConnectionError(pending["error"])
            return pending["target"]
        finally:
            with self.lock:
                if self.pending is pending:
                    self.pending = None

    def close(self):
        self.closed.set()
        with self.lock:
            if self.pending:
                self.pending["error"] = "앱의 번역 연결이 종료되었습니다."
                self.pending["done"].set()
        # Shutdown off the UI thread; no user's existing Chrome processes are killed.
        def shutdown():
            self.server.shutdown()
            self.server.server_close()
        Thread(target=shutdown, daemon=True).start()
