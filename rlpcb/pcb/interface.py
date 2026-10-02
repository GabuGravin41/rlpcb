"""Change notices between the electronics and the mechanical side of a product.

The two sides share two files in the board's KiCad project: `<board>.mech.json` (what the board is, written by RL PCB)
and `enclosure.json` (the space the product gives it, written by RL CAD). When either side rewrites its file, the
difference is appended to `interface_log.json` in the same folder, in plain words, with the checks on the other side
that it can affect. The other side reads the entries it has not seen yet ("the electronics moved J2 4 mm towards +x;
re-check connector access"), runs its checks, and marks them as seen with the result.

This file is kept identical in RL PCB (rlpcb/pcb/interface.py) and RL CAD (rlcad/interface.py).
"""
from __future__ import annotations

import json
import math
import os
import time
import uuid
from typing import Dict, List, Optional

LOG = "interface_log.json"


def _d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def mech_diff(old: Optional[Dict], new: Dict) -> List[Dict]:
    """Differences between two rl-mech/1 descriptions of a board, each with the mechanical checks it affects."""
    if not old:
        return []
    out = []
    so, sn = old.get("outline_mm", {}).get("size"), new.get("outline_mm", {}).get("size")
    if so and sn and (abs(so[0] - sn[0]) > 0.05 or abs(so[1] - sn[1]) > 0.05):
        out.append({"what": "outline", "detail": f"board size {so[0]}×{so[1]} → {sn[0]}×{sn[1]} mm",
                    "affects": ["board_fit", "enclosure size"]})
    ho = {h.get("ref") or str(h["at_mm"]): h for h in old.get("mounting_holes", [])}
    hn = {h.get("ref") or str(h["at_mm"]): h for h in new.get("mounting_holes", [])}
    for k in sorted(set(ho) | set(hn)):
        if k not in hn:
            out.append({"what": "mounting hole", "detail": f"{k} removed", "affects": ["board_mount"]})
        elif k not in ho:
            out.append({"what": "mounting hole", "detail": f"{k} added at {hn[k]['at_mm']}", "affects": ["board_mount"]})
        elif _d(ho[k]["at_mm"], hn[k]["at_mm"]) > 0.05 or abs(ho[k].get("drill_mm", 0) - hn[k].get("drill_mm", 0)) > 0.05:
            out.append({"what": "mounting hole", "detail": f"{k} {ho[k]['at_mm']} Ø{ho[k].get('drill_mm')} → "
                        f"{hn[k]['at_mm']} Ø{hn[k].get('drill_mm')}", "affects": ["board_mount"]})
    for side in ("top", "bottom"):
        a, b = old.get("height_mm", {}).get(side), new.get("height_mm", {}).get(side)
        if a is not None and b is not None and abs(a - b) > 0.1:
            out.append({"what": "part height", "detail": f"tallest part on the {side}: {a} → {b} mm",
                        "affects": ["board_height"]})
    co = {c["ref"]: c for c in old.get("connectors", [])}
    cn = {c["ref"]: c for c in new.get("connectors", [])}
    for r in sorted(set(co) | set(cn)):
        if r not in cn:
            out.append({"what": "connector", "detail": f"{r} ({co[r].get('mate')}) removed",
                        "affects": ["connector_access", "board_ports", "cutouts"]})
            continue
        if r not in co:
            out.append({"what": "connector", "detail": f"{r} ({cn[r].get('mate')}) added on edge {cn[r].get('edge')} at "
                        f"{cn[r].get('at_mm')}", "affects": ["connector_access", "board_ports", "cutouts"]})
            continue
        a, b = co[r], cn[r]
        bits = []
        if _d(a["at_mm"], b["at_mm"]) > 0.2:
            bits.append(f"moved {a['at_mm']} → {b['at_mm']} ({_d(a['at_mm'], b['at_mm']):.1f} mm)")
        if a.get("edge") != b.get("edge"):
            bits.append(f"now faces {b.get('edge')} (was {a.get('edge')})")
        if a.get("mate") != b.get("mate"):
            bits.append(f"mate {a.get('mate')} → {b.get('mate')}")
        if a.get("populated") != b.get("populated"):
            bits.append("now fitted" if b.get("populated") else "no longer fitted")
        if a.get("side") != b.get("side"):
            bits.append(f"moved to the {b.get('side')} side")
        if bits:
            out.append({"what": "connector", "detail": f"{r} ({b.get('mate')}): " + "; ".join(bits),
                        "affects": ["connector_access", "board_ports", "cutouts"]})
    ma, mb = old.get("mass_g_est"), new.get("mass_g_est")
    if ma is not None and mb is not None and abs(ma - mb) > 0.5:
        out.append({"what": "mass", "detail": f"{ma} → {mb} g", "affects": ["mass", "cg"]})
    return out


def envelope_diff(old: Optional[Dict], new: Dict) -> List[Dict]:
    """Differences between two rl-envelope/1 files, each with the board checks it affects."""
    if not old:
        return []
    out = []
    a, b = old.get("max_outline_mm"), new.get("max_outline_mm")
    if a and b and (abs(a[0] - b[0]) > 0.1 or abs(a[1] - b[1]) > 0.1):
        out.append({"what": "space for the board", "detail": f"largest outline {a[0]}×{a[1]} → {b[0]}×{b[1]} mm",
                    "affects": ["mech_outline"]})
    if old.get("mount_pattern_mm") != new.get("mount_pattern_mm"):
        out.append({"what": "mounting pattern", "detail": f"{old.get('mount_pattern_mm')} → {new.get('mount_pattern_mm')} mm",
                    "affects": ["mech_mounting"]})
    for side in ("top", "bottom"):
        x, y = old.get("keepout_height_mm", {}).get(side), new.get("keepout_height_mm", {}).get(side)
        if x is not None and y is not None and abs(x - y) > 0.1:
            out.append({"what": "height allowed", "detail": f"{side}: {x} → {y} mm" + (" (less room)" if y < x else ""),
                        "affects": ["mech_height"]})
    if sorted(old.get("reachable_edges", [])) != sorted(new.get("reachable_edges", [])):
        out.append({"what": "reachable edges", "detail": f"{old.get('reachable_edges')} → {new.get('reachable_edges')}",
                    "affects": ["mech_port"]})
    pa = {(p.get("mate"), bool(p.get("via_extension"))) for p in old.get("required_ports", [])}
    pb = {(p.get("mate"), bool(p.get("via_extension"))) for p in new.get("required_ports", [])}
    if pa != pb:
        out.append({"what": "required ports", "detail": f"{sorted(pa)} → {sorted(pb)}", "affects": ["mech_port"]})
    return out


# ------------------------------------------------------------------------------------------- the shared log
def _log_path(project_dir: str) -> str:
    return os.path.join(project_dir, LOG)


def read_log(project_dir: str) -> Dict:
    try:
        with open(_log_path(project_dir), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("schema", "rl-interface-log/1")
    d.setdefault("entries", [])
    return d


def _write(project_dir: str, d: Dict):
    with open(_log_path(project_dir), "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


def record(project_dir: str, side: str, file: str, changes: List[Dict], note: str = "") -> Optional[Dict]:
    """Append a change notice from `side` ('pcb' or 'cad') if anything changed."""
    if not changes:
        return None
    d = read_log(project_dir)
    e = {"id": uuid.uuid4().hex[:8], "t": round(time.time(), 1), "date": time.strftime("%Y-%m-%d %H:%M"),
         "from": side, "file": file, "changes": changes, "note": note, "seen_by_other_side": None}
    d["entries"].append(e)
    _write(project_dir, d)
    return e


def unseen(project_dir: str, by_side: str) -> List[Dict]:
    """Notices from the other side that `by_side` has not acknowledged."""
    return [e for e in read_log(project_dir)["entries"] if e["from"] != by_side and not e.get("seen_by_other_side")]


def mark_seen(project_dir: str, by_side: str, ids: List[str], result: str = "") -> int:
    d = read_log(project_dir)
    n = 0
    for e in d["entries"]:
        if e["id"] in ids and e["from"] != by_side and not e.get("seen_by_other_side"):
            e["seen_by_other_side"] = {"t": round(time.time(), 1), "result": result}
            n += 1
    if n:
        _write(project_dir, d)
    return n


def write_with_notice(path: str, data: Dict, side: str, differ, note: str = "") -> Optional[Dict]:
    """Write a JSON interface file; if a previous version existed, record what changed."""
    old = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError):
            old = None
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return record(os.path.dirname(os.path.abspath(path)), side, os.path.basename(path), differ(old, data), note)
