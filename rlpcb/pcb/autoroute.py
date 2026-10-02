"""Autorouting through Freerouting (Specctra DSN/SES round trip).

Pipeline:
  1. export .dsn using KiCad's own Python (pcbnew.ExportSpecctraDSN) — runs in KiCad's
     bundled interpreter so it works on Windows without extra setup;
  2. run freerouting.jar headless (Java 21+), which writes a .ses session file;
  3. import the .ses back (pcbnew.ImportSpecctraSES) into a *copy* of the board
     (<name>.routed.kicad_pcb) so the original is never overwritten.

The copilot recommends routing critical nets by hand first (power, high-speed,
diff pairs, analog), locking them, and letting the autorouter finish the rest.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
import textwrap
import urllib.request
from typing import Dict, Optional

from ..config import data_dir, load_settings
from ..kicad.paths import kicad_python

FREEROUTING_URL = "https://github.com/freerouting/freerouting/releases/download/v2.1.0/freerouting-2.1.0.jar"

_EXPORT = textwrap.dedent("""
    import sys, pcbnew
    b = pcbnew.LoadBoard(sys.argv[1])
    ok = pcbnew.ExportSpecctraDSN(b, sys.argv[2])
    print("OK" if ok else "FAIL")
""")

_IMPORT = textwrap.dedent("""
    import sys, pcbnew
    b = pcbnew.LoadBoard(sys.argv[1])
    ok = pcbnew.ImportSpecctraSES(b, sys.argv[2])
    if ok:
        pcbnew.SaveBoard(sys.argv[3], b)
    print("OK" if ok else "FAIL")
""")


def find_java() -> Optional[str]:
    j = shutil.which("java")
    if j:
        return j
    for base in (os.environ.get("JAVA_HOME", ""), r"C:\Program Files\Java", r"C:\Program Files\Eclipse Adoptium",
                 r"C:\Program Files\Microsoft"):
        if base and os.path.isdir(base):
            hits = glob.glob(os.path.join(base, "**", "bin", "java.exe"), recursive=True)
            if hits:
                return sorted(hits)[-1]
    return None


def freerouting_jar(download: bool = False) -> Optional[str]:
    s = load_settings()
    if s.get("freerouting_jar") and os.path.exists(s["freerouting_jar"]):
        return s["freerouting_jar"]
    local = os.path.join(data_dir(), "freerouting.jar")
    if os.path.exists(local):
        return local
    if download:
        urllib.request.urlretrieve(FREEROUTING_URL, local)
        return local
    return None


def _py(script: str, *args, timeout=600) -> subprocess.CompletedProcess:
    py = kicad_python()
    if not py:
        # Linux distro packages put pcbnew in the system python
        py = shutil.which("python3") or shutil.which("python")
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    f.write(script)
    f.close()
    return subprocess.run([py, f.name, *args], capture_output=True, text=True, timeout=timeout)


def export_dsn(pcb_path: str, dsn_path: Optional[str] = None) -> str:
    dsn_path = dsn_path or os.path.splitext(pcb_path)[0] + ".dsn"
    r = _py(_EXPORT, pcb_path, dsn_path)
    if "OK" not in r.stdout or not os.path.exists(dsn_path):
        raise RuntimeError(f"DSN export failed: {r.stderr[-800:] or r.stdout[-400:]}")
    return dsn_path


def run_freerouting(dsn_path: str, max_passes: int = 100, threads: int = 4, time_limit_min: float = 10) -> str:
    java = find_java()
    if not java:
        raise RuntimeError("Java 21+ is required for Freerouting. Install e.g. Eclipse Temurin 21 and retry.")
    jar = freerouting_jar(download=True)
    ses = os.path.splitext(dsn_path)[0] + ".ses"
    # Freerouting 2.x headless jobs ignore -mp; they stop when fully routed or at router.job_timeout, then save the
    # session. (1.x honours -mp and ignores the unknown setting.)
    secs = max(60, int(time_limit_min * 60))
    limit = f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"
    args = [java, "-jar", jar, "-de", dsn_path, "-do", ses, "-mp", str(max_passes), "-mt", str(threads),
            "--gui.enabled=false", f"--router.job_timeout={limit}"]
    if os.path.exists(ses):
        os.remove(ses)
    r = subprocess.run(args, capture_output=True, text=True, timeout=secs + 300)
    if not os.path.exists(ses):
        raise RuntimeError(f"Freerouting produced no session file:\n{(r.stderr or r.stdout)[-1500:]}")
    return ses


def import_ses(pcb_path: str, ses_path: str, out_path: Optional[str] = None) -> str:
    out_path = out_path or os.path.splitext(pcb_path)[0] + ".routed.kicad_pcb"
    r = _py(_IMPORT, pcb_path, ses_path, out_path)
    if "OK" not in r.stdout:
        raise RuntimeError(f"SES import failed: {r.stderr[-800:] or r.stdout[-400:]}")
    return out_path


def import_ses_text(pcb_path: str, ses_path: str, dsn_path: str, out_path: Optional[str] = None) -> str:
    """Pure-Python SES importer (no pcbnew needed): appends routed segments and vias to a copy of the board."""
    import re
    import uuid as uuidlib

    from ..kicad.sexpr import parse, QStr, dump
    out_path = out_path or os.path.splitext(pcb_path)[0] + ".routed.kicad_pcb"
    def _load_specctra(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            t = fh.read()
        return parse(re.sub(r'\(string_quote\s+"\s*\)', "(string_quote Q)", t))
    ses = _load_specctra(ses_path)
    dsn = _load_specctra(dsn_path)
    with open(pcb_path, encoding="utf-8") as f:
        text = f.read()
    board = parse(text)
    # DSN layer order -> KiCad copper names
    dsn_layers = [str(l.items[1]) for l in dsn.child("structure").children("layer")]
    cu = [str(l.items[1]) for l in board.child("layers").children() if str(l.items[1]).endswith(".Cu")]
    order = ["F.Cu"] + [c for c in cu if c.startswith("In")] + ["B.Cu"]
    order = [c for c in order if c in cu] or cu
    lmap = {name: order[i] if i < len(order) else order[-1] for i, name in enumerate(dsn_layers)}
    for name in dsn_layers:  # layer names that already are KiCad names
        if name in cu:
            lmap[name] = name
    res = 10000.0
    for r in ses.find_all("resolution"):
        unit, val = str(r.items[1]), float(r.items[2])
        scale = {"um": 1e-3, "mm": 1.0, "mil": 0.0254, "inch": 25.4, "cm": 10.0}.get(unit, 1e-3)
        res = val / scale  # units per mm
        break
    codes = {str(n.items[2]): str(n.items[1]) for n in board.children("net") if len(n.items) >= 3}
    v8 = int(board.value("version", "0") or 0) >= 20231120

    def net_node(name):
        if codes:
            return ["net", int(codes.get(name, "0"))]
        return ["net", QStr(name)]

    def uid():
        return ["uuid", QStr(str(uuidlib.uuid4()))] if v8 else ["tstamp", str(uuidlib.uuid4())]
    items = []
    nseg = nvia = 0
    no = ses.child("routes")
    no = no.child("network_out") if no is not None else None
    for net in (no.children("net") if no is not None else []):
        name = str(net.items[1])
        for w in net.children("wire"):
            path = w.child("path")
            if path is None:
                continue
            layer = lmap.get(str(path.items[1]), "F.Cu")
            width = float(path.items[2]) / res
            nums = [float(a) for a in path.items[3:] if not hasattr(a, "items")]
            pts = [(nums[i] / res, -nums[i + 1] / res) for i in range(0, len(nums) - 1, 2)]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                items.append(["segment", ["start", round(x1, 4), round(y1, 4)], ["end", round(x2, 4), round(y2, 4)],
                              ["width", round(width, 4)], ["layer", QStr(layer)], net_node(name), uid()])
                nseg += 1
        for v in net.children("via"):
            m = re.search(r"_(\d+):(\d+)_um", str(v.items[1]))
            size, drill = (int(m.group(1)) / 1000, int(m.group(2)) / 1000) if m else (0.6, 0.3)
            x, y = float(v.items[2]) / res, -float(v.items[3]) / res
            items.append(["via", ["at", round(x, 4), round(y, 4)], ["size", size], ["drill", drill],
                          ["layers", QStr("F.Cu"), QStr("B.Cu")], net_node(name), uid()])
            nvia += 1
    anchor = board.end - 1
    block = "".join("\t" + dump(i, 1) + "\n" for i in items)
    text = text[:anchor] + block + text[anchor:]
    parse(text)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return out_path, nseg, nvia


def autoroute(pcb_path: str, max_passes: int = 100, time_limit_min: float = 10) -> Dict:
    dsn = export_dsn(pcb_path)
    ses = run_freerouting(dsn, max_passes=max_passes, time_limit_min=time_limit_min)
    try:
        out = import_ses(pcb_path, ses)
    except Exception:
        out, _, _ = import_ses_text(pcb_path, ses, dsn)
    stats = {}
    try:
        from .board import Board
        b = Board(out)
        stats = b.routing_status()
    except Exception:  # noqa
        pass
    return {"dsn": dsn, "ses": ses, "routed_board": out, "routing": stats,
            "next_steps": ["Open the routed copy in KiCad and run DRC.",
                           "Unrouted connections left: route them by hand (often a sign that placement needs space "
                           "or another signal layer), or move parts and re-run.",
                           "Review every power and high-speed path by eye; autorouters don't understand return paths, "
                           "loop areas or impedance.",
                           "If it looks good, rename the routed copy over the original (keep a backup)."]}
