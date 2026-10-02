"""Shared launcher logic for the KiCad plugins (stdlib only — runs inside KiCad's Python).

Reads ~/.rlpcb/launcher.json (written by the installer):
  {"python": "<path to RL PCB venv python>", "repo": "<rlpcb folder>", "port": 8765}
Starts the RL PCB server if it is not running, then opens the chat panel.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser

CFG = os.path.join(os.path.expanduser("~"), ".rlpcb", "launcher.json")


def config():
    try:
        with open(CFG, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def base_url():
    return f"http://127.0.0.1:{config().get('port', 8765)}"


def server_up(timeout=0.8):
    try:
        with urllib.request.urlopen(base_url() + "/api/status", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_server():
    if server_up():
        return True
    cfg = config()
    py = cfg.get("python")
    repo = cfg.get("repo")
    if not py or not os.path.exists(py):
        raise RuntimeError("RL PCB is not installed for this user (missing ~/.rlpcb/launcher.json). Run install_windows.ps1.")
    if os.name == "nt":
        pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
        if os.path.exists(pyw):
            py = pyw
    kw = {"cwd": repo or None}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    log = open(os.path.join(os.path.expanduser("~"), ".rlpcb", "server.log"), "a")
    subprocess.Popen([py, "-m", "rlpcb.agent.server", "--port", str(cfg.get("port", 8765))], stdout=log, stderr=log, **kw)
    for _ in range(60):
        time.sleep(0.25)
        if server_up():
            return True
    raise RuntimeError("RL PCB server did not start; see ~/.rlpcb/server.log")


def tell_project(path):
    if not path:
        return
    try:
        req = urllib.request.Request(base_url() + "/api/open", data=json.dumps({"path": path}).encode(),
                                     headers={"content-type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


def open_window(project_path=""):
    url = base_url() + "/" + (("?project=" + urllib.parse.quote(project_path)) if project_path else "")
    cands = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")):
            cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                      os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    else:
        cands += [shutil.which(x) or "" for x in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser")]
    for c in cands:
        if c and os.path.exists(c):
            subprocess.Popen([c, f"--app={url}", "--window-size=520,900"])
            return url
    webbrowser.open(url)
    return url
