"""Local HTTP server for the RL PCB chat panel (stdlib only).

python -m rlpcb.agent.server [--port 8765] [--open]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..config import REPO_DIR, data_dir, load_settings, save_settings
from .chat import Conversation, list_conversations
from .tools import TOOLS, Session, run_tool

WEB_DIR = os.path.join(REPO_DIR, "web")
SESSION = Session()
CONVS = {}
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "RLPCB/0.1"

    def log_message(self, fmt, *args):  # quiet
        pass

    # ------------------------------------------------------------- helpers
    def _json(self, obj, code=200):
        b = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode() or "{}")

    def _local_only(self):
        """Only this machine, only our own page: blocks DNS-rebinding and cross-site requests from browser tabs."""
        host = self.client_address[0]
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        if host not in ("127.0.0.1", "::1", "localhost") or self.headers.get("Host", "") not in allowed:
            self._json({"error": "local connections only"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin.split("//", 1)[-1] not in allowed:
            self._json({"error": "cross-origin request refused"}, 403)
            return False
        if self.command == "POST" and not (self.headers.get("Content-Type", "").startswith("application/json")):
            self._json({"error": "JSON only"}, 415)
            return False
        return True

    # ------------------------------------------------------------- GET
    def do_GET(self):
        if not self._local_only():
            return
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            return self._file(os.path.join(WEB_DIR, "chat.html"), "text/html; charset=utf-8")
        if u.path == "/api/status":
            s = load_settings()
            return self._json({"project": SESSION.project, "provider": s.get("provider"), "model": s.get("model"),
                               "has_key": bool(s.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")),
                               "tools": len(TOOLS)})
        if u.path == "/api/conversations":
            return self._json(list_conversations())
        if u.path == "/api/conversation":
            cid = q.get("id", [""])[0]
            if not re.fullmatch(r"[\w-]{1,64}", cid):
                return self._json({"error": "bad id"}, 400)
            c = Conversation(SESSION, cid)
            return self._json({"id": c.id, "messages": _display_messages(c.messages)})
        if u.path == "/api/settings":
            s = dict(load_settings())
            for k in ("anthropic_api_key", "openai_api_key", "github_token"):
                if s.get(k):
                    s[k] = "••••" + s[k][-4:]
            return self._json(s)
        if u.path == "/api/tools":
            return self._json([{"name": t.name, "description": t.description} for t in TOOLS])
        if u.path == "/api/image":
            p = os.path.abspath(q.get("path", [""])[0])
            import tempfile
            roots = [os.path.abspath(tempfile.gettempdir()), os.path.abspath(data_dir())]
            if SESSION.project_dir:
                roots.append(os.path.abspath(SESSION.project_dir))
            inside = any(os.path.normcase(p).startswith(os.path.normcase(r) + os.sep) for r in roots)
            if inside and p.lower().endswith((".png", ".svg")) and os.path.exists(p):
                return self._file(p, "image/png" if p.endswith(".png") else "image/svg+xml")
            return self._json({"error": "not found"}, 404)
        self._json({"error": "not found"}, 404)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                b = f.read()
        except OSError:
            return self._json({"error": "missing " + path}, 404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    # ------------------------------------------------------------- POST
    def do_POST(self):
        if not self._local_only():
            return
        u = urllib.parse.urlparse(self.path)
        body = self._body()
        if u.path == "/api/chat":
            return self._chat(body)
        if u.path == "/api/tool":
            res = run_tool(SESSION, body.get("name", ""), body.get("args") or {})
            return self._json(res)
        if u.path == "/api/engineer":
            # the engineer's own decisions from the panel: mode, accept/reject, undo (journalled as 'engineer')
            name = body.get("name", "")
            if name not in ("copilot_mode", "proposal_accept", "proposal_reject", "undo", "proposals", "copilot_status",
                            "proposal_show", "design_journal"):
                return self._json({"error": "not an engineer action"}, 400)
            return self._json(run_tool(SESSION, name, body.get("args") or {}, actor="engineer"))
        if u.path == "/api/open":
            res = run_tool(SESSION, "open_project", {"path": body.get("path", "")})
            return self._json(res)
        if u.path == "/api/settings":
            clean = {k: v for k, v in body.items() if not (isinstance(v, str) and v.startswith("••••"))}
            s = save_settings(clean)
            SESSION.settings = s
            return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

    def _chat(self, body):
        cid = body.get("conv_id") or None
        if cid and not re.fullmatch(r"[\w-]{1,64}", str(cid)):
            return self._json({"error": "bad conversation id"}, 400)
        with LOCK:
            conv = CONVS.get(cid) if cid else None
            if conv is None:
                conv = Conversation(SESSION, cid)
                CONVS[conv.id] = conv
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(ev):
            try:
                ev["conv_id"] = conv.id
                self.wfile.write(f"data: {json.dumps(ev, default=str)}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        conv.send(body.get("text", ""), emit, body.get("context"))


def _display_messages(msgs):
    out = []
    for m in msgs:
        c = m.get("content")
        if isinstance(c, str):
            out.append({"role": m["role"], "text": c})
        elif isinstance(c, list):
            for b in c:
                if b.get("type") == "text":
                    out.append({"role": m["role"], "text": b["text"]})
                elif b.get("type") == "tool_use":
                    out.append({"role": "tool", "text": f"{b['name']}"})
    return out


def serve(port: int = 8765, open_browser: bool = False):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"RL PCB panel running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: open_panel(url)).start()
    httpd.serve_forever()


def open_panel(url: str):
    """Open as a chromeless app window (Edge/Chrome --app) when possible, else the default browser."""
    import shutil
    import subprocess
    cands = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")):
            cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                      os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    cands += [shutil.which(x) or "" for x in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser")]
    for c in cands:
        if c and os.path.exists(c):
            subprocess.Popen([c, f"--app={url}", "--window-size=520,900"])
            return
    webbrowser.open(url)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=load_settings().get("server_port", 8765))
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()
    serve(a.port, a.open)


if __name__ == "__main__":
    main()
