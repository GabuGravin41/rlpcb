"""Thin wrapper around kicad-cli (KiCad 7+; ERC/DRC need KiCad 8+)."""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import tempfile
from typing import Dict, List, Optional

from .paths import kicad_cli


class KiCadCLIError(RuntimeError):
    pass


def _run(args: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    exe = kicad_cli()
    if not exe:
        raise KiCadCLIError("kicad-cli not found. Install KiCad 8+ or set RLPCB_KICAD_CLI to its path.")
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, **kw)


def version() -> Optional[str]:
    try:
        r = _run(["version"], timeout=30)
        return (r.stdout or r.stderr).strip()
    except Exception:
        return None


def major() -> int:
    v = version() or ""
    m = re.match(r"(\d+)", v)
    return int(m.group(1)) if m else 0


def erc(sch_path: str) -> Dict:
    out = tempfile.mktemp(suffix=".json")
    r = _run(["sch", "erc", "--format", "json", "--severity-all", "-o", out, sch_path])
    if not os.path.exists(out):
        raise KiCadCLIError(f"ERC failed (KiCad 8+ required): {r.stderr.strip() or r.stdout.strip()}")
    with open(out, encoding="utf-8") as f:
        data = json.load(f)
    return _summarize_report(data, "erc")


def drc(pcb_path: str, schematic_parity: bool = True, refill_zones: bool = True) -> Dict:
    out = tempfile.mktemp(suffix=".json")
    args = ["pcb", "drc", "--format", "json", "--severity-all", "-o", out]
    if schematic_parity:
        args.append("--schematic-parity")
    if refill_zones:
        args.append("--refill-zones")
    r = _run(args + [pcb_path])
    if not os.path.exists(out):
        raise KiCadCLIError(f"DRC failed (KiCad 8+ required): {r.stderr.strip() or r.stdout.strip()}")
    with open(out, encoding="utf-8") as f:
        data = json.load(f)
    return _summarize_report(data, "drc")


def _summarize_report(data: Dict, kind: str) -> Dict:
    groups: Dict[str, list] = {}
    counts: Dict[str, int] = {}
    items = []
    for key in ("violations", "unconnected_items", "schematic_parity"):
        for v in data.get(key, []) or []:
            v = dict(v)
            v["_group"] = key
            items.append(v)
    for sheet in data.get("sheets", []) or []:
        for v in sheet.get("violations", []):
            v = dict(v)
            v["_group"] = "violations"
            v["sheet"] = sheet.get("path", "")
            items.append(v)
    for v in items:
        t = v.get("type", "?")
        counts[t] = counts.get(t, 0) + 1
        g = groups.setdefault(t, [])
        if len(g) < 12:
            g.append({"severity": v.get("severity"), "description": v.get("description"), "sheet": v.get("sheet", ""),
                      "items": [(i.get("description"), i.get("pos")) for i in v.get("items", [])][:4]})
    sev = {}
    for v in items:
        sev[v.get("severity", "?")] = sev.get(v.get("severity", "?"), 0) + 1
    return {"kind": kind, "total": len(items), "by_severity": sev, "by_type": counts, "examples": groups,
            "kicad_version": data.get("kicad_version")}


def export_netlist(sch_path: str) -> str:
    out = tempfile.mktemp(suffix=".net")
    _run(["sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, sch_path])
    if not os.path.exists(out):
        raise KiCadCLIError("netlist export failed")
    return out


def export_sch_svg(sch_path: str, out_dir: Optional[str] = None) -> List[str]:
    out_dir = out_dir or tempfile.mkdtemp(prefix="rlpcb_svg_")
    r = _run(["sch", "export", "svg", "-o", out_dir, sch_path])
    files = sorted(glob.glob(os.path.join(out_dir, "*.svg")))
    if not files:
        raise KiCadCLIError(f"SVG export failed: {r.stderr.strip()}")
    return files


def export_sch_pdf(sch_path: str, out: Optional[str] = None) -> str:
    out = out or tempfile.mktemp(suffix=".pdf")
    r = _run(["sch", "export", "pdf", "-o", out, sch_path])
    if not os.path.exists(out):
        raise KiCadCLIError(f"PDF export failed: {r.stderr.strip()}")
    return out


def export_pcb_svg(pcb_path: str, layers: str = "F.Cu,B.Cu,F.SilkS,Edge.Cuts", out: Optional[str] = None) -> str:
    out = out or tempfile.mktemp(suffix=".svg")
    args = ["pcb", "export", "svg", "--layers", layers, "--exclude-drawing-sheet", "-o", out, pcb_path]
    r = _run(args)
    if not os.path.exists(out):
        # KiCad 9 changed option names; try the per-layer mode fallback
        r2 = _run(["pcb", "export", "svg", "--layers", layers, "--mode-single", "-o", out, pcb_path])
        if not os.path.exists(out):
            raise KiCadCLIError(f"PCB SVG export failed: {r.stderr.strip()} {r2.stderr.strip()}")
    return out


def export_fab(pcb_path: str, out_dir: str) -> Dict[str, str]:
    """Gerbers + drill + position files + (if available) IPC-2581 — a manufacturing package."""
    os.makedirs(out_dir, exist_ok=True)
    res = {}
    g = os.path.join(out_dir, "gerbers")
    os.makedirs(g, exist_ok=True)
    r = _run(["pcb", "export", "gerbers", "-o", g + os.sep, pcb_path])
    res["gerbers"] = g if glob.glob(os.path.join(g, "*")) else f"failed: {r.stderr.strip()}"
    r = _run(["pcb", "export", "drill", "-o", g + os.sep, pcb_path])
    res["drill"] = "ok" if glob.glob(os.path.join(g, "*.drl")) else f"failed: {r.stderr.strip()}"
    pos = os.path.join(out_dir, "positions.csv")
    r = _run(["pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "-o", pos, pcb_path])
    res["positions"] = pos if os.path.exists(pos) else f"failed: {r.stderr.strip()}"
    step = os.path.join(out_dir, "board.step")
    r = _run(["pcb", "export", "step", "-o", step, pcb_path], timeout=900)
    res["step"] = step if os.path.exists(step) else f"skipped: {r.stderr.strip()[:200]}"
    return res


def export_bom(sch_path: str, out: str) -> str:
    r = _run(["sch", "export", "bom", "-o", out, sch_path])
    if not os.path.exists(out):
        raise KiCadCLIError(f"BOM export failed (KiCad 8+): {r.stderr.strip()}")
    return out
