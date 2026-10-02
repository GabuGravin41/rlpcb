"""Widen power tracks towards the width their current needs, as far as KiCad's DRC allows (runs in KiCad's Python).

For each net, the tracks narrower than the target are tried at each width in turn (widest first); after every
attempt a full DRC decides which segments fit, and the ones that do not fall back to the next width, down to their
original width. Nothing that passed DRC before can fail after: a segment only keeps a width that DRC accepted.

    python -m rlpcb.pcb.widen in.kicad_pcb out.kicad_pcb report.rpt NET:1.4,1.2,1.0 +5V:1.0,0.8,0.6
"""
from __future__ import annotations

import json
import re
import sys
from typing import Dict, List

import pcbnew

from .finish import run_drc

MM, TM = pcbnew.FromMM, pcbnew.ToMM
BAD = ("[clearance]", "[hole_clearance]", "[copper_edge_clearance]", "[solder_mask_bridge]", "[shorting_items]",
       "[tracks_crossing]")


def widen(src: str, dst: str, targets: Dict[str, List[float]], report: str) -> Dict:
    b = pcbnew.LoadBoard(src)
    before = sum(1 for bl in run_drc(b, report) if bl.startswith(BAD))
    tracks = list(b.GetTracks())
    out = {}
    for net, widths in targets.items():
        segs = [t for t in tracks if t.GetNetname() == net and t.Type() != pcbnew.PCB_VIA_T
                and TM(t.GetWidth()) < widths[0] - 1e-6]
        orig = {id(t): t.GetWidth() for t in segs}
        pending, kept = list(segs), {}
        for w in widths:
            for t in pending:
                if TM(orig[id(t)]) < w:
                    t.SetWidth(MM(w))
            bad = set()
            for bl in run_drc(b, report):
                if not bl.startswith(BAD):
                    continue
                for m in re.finditer(r"@\(([\d.\-]+) mm, ([\d.\-]+) mm\): Track \[([^\]]+)\]", bl):
                    if m.group(3) != net:
                        continue
                    x, y = float(m.group(1)), float(m.group(2))
                    for t in pending:
                        s = t.GetStart()
                        if abs(TM(s.x) - x) < 0.01 and abs(TM(s.y) - y) < 0.01:
                            bad.add(id(t))
            for t in pending:
                if id(t) in bad:
                    t.SetWidth(orig[id(t)])
                elif TM(orig[id(t)]) < w:
                    kept[w] = kept.get(w, 0) + 1
            pending = [t for t in pending if id(t) in bad]
            if not pending:
                break
        out[net] = {"candidates": len(segs), "widened": {str(k): v for k, v in kept.items()},
                    "left_narrow": len(pending)}
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(dst)
    blocks = run_drc(b, report)
    errors = sum(1 for bl in blocks if bl.startswith(BAD))
    return {"nets": out, "clearance_errors_before": before, "clearance_errors_after": errors, "out": dst,
            "note": "errors that were there before (for example a net that now belongs to a class with a larger "
                    "clearance) are not caused by widening; run_drc lists them"}


if __name__ == "__main__":
    a = sys.argv[1:]
    tg = {}
    for spec in a[3:]:
        net, ws = spec.rsplit(":", 1)
        tg[net] = [float(w) for w in ws.split(",")]
    print(json.dumps(widen(a[0], a[1], tg, a[2]), indent=1))
