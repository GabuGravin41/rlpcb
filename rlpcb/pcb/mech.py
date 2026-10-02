"""Mechanical interface between a board (RL PCB / KiCad) and the product around it (RL CAD / any MCAD).

Two small JSON files are the meeting point; neither tool needs the other installed to read them.

  <project>/<name>.mech.json      written here from the .kicad_pcb        schema "rl-mech/1"
      what the board IS: outline, thickness, mounting holes, connectors (position, which edge they face, mate type),
      component height per side, estimated mass.
  <project>/enclosure.json        written by RL CAD from the airframe       schema "rl-envelope/1"
      what the product ALLOWS: maximum outline, mounting pattern, height keep-outs above/below, which edges can be
      reached from outside, and which connectors must be reachable.

Coordinates in both files: millimetres, origin at the board outline's centre, +x = KiCad +x, +y = KiCad -y (so the
frame matches KiCad's STEP export), z = 0 on the board's bottom face, top face at z = thickness.
Edges: "+x" (KiCad right), "-x" (left), "+y" (KiCad top edge), "-y" (KiCad bottom edge).
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Dict, List, Optional

from .board import Board

MECH_SCHEMA = "rl-mech/1"
ENVELOPE_SCHEMA = "rl-envelope/1"

# typical component heights above the copper (mm), by footprint name; first match wins. "est" when unknown.
HEIGHTS = [
    (r"MountingHole|SolderWire|TestPoint|Fiducial", 0.0),
    (r"USB_C_Receptacle_GCT_USB4105", 3.31), (r"USB_C", 3.3), (r"USB_Micro", 2.8),
    (r"JST_SH_.*Horizontal", 2.95), (r"JST_SH_.*Vertical", 4.25), (r"JST_GH", 4.25), (r"JST_PH", 6.0),
    (r"PinHeader_1x\d+_P1\.27mm_Vertical", 4.4), (r"PinHeader_.*P2\.54mm_Vertical", 8.5),
    (r"L_Bourns_SRP7028A", 2.8), (r"L_Bourns_SRP", 3.0), (r"L_\w*_(\d)x", 3.0),
    (r"SW_SPST_TL3342", 2.5), (r"SW_", 2.0),
    (r"D_SMA", 2.3), (r"D_SMB", 2.4), (r"D_SMC", 2.4), (r"D_SOD-123", 1.35), (r"D_SOD-323", 1.1),
    (r"LQFP", 1.6), (r"TQFP", 1.2), (r"QFN|DFN", 1.0), (r"SOIC-8_5\.23", 2.16), (r"SOIC", 1.75),
    (r"SO-PowerPAD|HTSSOP|TSSOP", 1.2), (r"SOT-23", 1.45), (r"SOT-223", 1.8), (r"SOT-363|SC-70", 1.1),
    (r"LGA-16_3x3", 0.75), (r"Bosch_LGA-8", 0.95), (r"LGA", 1.0),
    (r"Crystal_SMD_3225", 0.8), (r"Crystal_SMD_2016", 0.6), (r"Crystal", 1.0),
    (r"C_1206", 1.6), (r"C_0805", 1.25), (r"C_0603", 0.9), (r"C_0402", 0.55),
    (r"R_1206", 0.6), (r"R_0805", 0.55), (r"R_0603", 0.5), (r"R_0402", 0.4),
    (r"L_0603|L_0402", 0.9), (r"LED_0603", 0.8), (r"LED_0402", 0.5), (r"LED", 1.0),
]
MATES = [(r"USB_C", "usb-c"), (r"USB_Micro", "usb-micro"), (r"JST_SH_.*?_1x(\d+)", "jst-sh-{0}"),
         (r"JST_GH_.*?_1x(\d+)", "jst-gh-{0}"), (r"SolderWire", "wire-pads"), (r"PinHeader_1x(\d+)", "header-{0}")]
# plug cross-section a user needs to reach the connector from outside (w × h, mm) and how deep it goes in
PLUGS = {"usb-c": (12.5, 7.0), "usb-micro": (11.0, 7.0)}


def _height(fpid: str):
    name = fpid.split(":")[-1]
    for pat, h in HEIGHTS:
        if re.search(pat, name):
            return h, "table"
    return 1.5, "est"


def _mate(fpid: str) -> Optional[str]:
    name = fpid.split(":")[-1]
    for pat, m in MATES:
        mm = re.search(pat, name)
        if mm:
            return m.format(*mm.groups())
    return None


def export_mechanical(pcb_path: str, out_path: Optional[str] = None, mass_g: Optional[float] = None) -> Dict:
    b = Board(pcb_path)
    x0, y0, x1, y1 = b.board_bbox()
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    t = b.thickness

    def P(x, y):                               # KiCad (y down) -> mech frame (centre origin, y up)
        return [round(x - cx, 3), round(cy - y, 3)]

    holes, comps, connectors = [], [], []
    h_top = h_bot = 0.0
    for f in b.footprints:
        side = "top" if f.layer.startswith("F") else "bottom"
        h, how = _height(f.fpid)
        attr = f.node.child("attr").atoms() if f.node is not None and f.node.child("attr") is not None else []
        populated = not (f.dnp or "exclude_from_bom" in attr)
        if not populated:
            h, how = 0.0, "not populated"
        if side == "top":
            h_top = max(h_top, h)
        else:
            h_bot = max(h_bot, h)
        c0, c1 = P(f.courtyard[0], f.courtyard[3]), P(f.courtyard[2], f.courtyard[1])
        comps.append({"ref": f.ref, "footprint": f.fpid.split(":")[-1], "side": side, "height_mm": h, "height_source": how,
                      "populated": populated,
                      "bbox_mm": [c0[0], c0[1], c1[0], c1[1]]})
        for p in f.pads:
            if p.drill and p.drill >= 2.0 and ("MountingHole" in f.fpid or not p.net):
                holes.append({"ref": f.ref, "at_mm": P(p.x, p.y), "drill_mm": p.drill,
                              "plated": p.kind == "thru_hole", "net": p.net})
        mate = _mate(f.fpid)
        if mate or re.match(r"^(J|P|CN|USB)\d", f.ref):
            # which edge does it face? the one its courtyard is closest to (or hangs over)
            d = {"+x": x1 - f.courtyard[2], "-x": f.courtyard[0] - x0, "+y": f.courtyard[1] - y0, "-y": y1 - f.courtyard[3]}
            edge, gap = min(d.items(), key=lambda kv: kv[1])
            nets = sorted({p.net for p in f.pads if p.net})
            connectors.append({"ref": f.ref, "value": f.value, "mate": mate, "side": side, "at_mm": P(f.x, f.y),
                               "rotation": f.angle, "bbox_mm": [c0[0], c0[1], c1[0], c1[1]],
                               "edge": edge if gap < 1.5 else None, "overhang_mm": round(max(0.0, -gap), 2),
                               "height_mm": h, "populated": populated, "plug_mm": PLUGS.get(mate or ""),
                               "nets": nets[:12]})
    area_cm2 = (x1 - x0) * (y1 - y0) / 100
    mech = {"schema": MECH_SCHEMA, "board": os.path.splitext(os.path.basename(pcb_path))[0],
            "source": os.path.abspath(pcb_path), "source_mtime": os.path.getmtime(pcb_path), "generated": time.time(),
            "frame": "origin at outline centre; +x KiCad +x; +y KiCad -y; z=0 bottom face",
            "outline_mm": {"size": [round(x1 - x0, 3), round(y1 - y0, 3)], "min": P(x0, y1), "max": P(x1, y0)},
            "kicad_centre_mm": [round(cx, 4), round(cy, 4)],     # KiCad STEP export puts this point at (x, -y)
            "thickness_mm": t, "copper_layers": len(b.copper_layers),
            "mounting_holes": holes,
            "height_mm": {"top": h_top, "bottom": h_bot},
            "connectors": connectors, "components": comps,
            "mass_g_est": mass_g if mass_g is not None else round(area_cm2 * t / 10 * 1.85 + 0.03 * len(b.footprints) + 1.5, 1),
            "notes": ["component heights come from a footprint-class table (height_source='table') or a 1.5 mm default "
                      "('est'); a KiCad STEP with 3D models replaces them"]}
    out_path = out_path or os.path.splitext(pcb_path)[0] + ".mech.json"
    from .interface import mech_diff, write_with_notice
    notice = write_with_notice(out_path, mech, "pcb", mech_diff)
    mech["path"] = out_path
    if notice:
        mech["_notice"] = notice
    return mech


def check_envelope(mech: Dict, env: Dict) -> Dict:
    """Does the board fit the space the product gives it? Findings in RL PCB's usual shape."""
    out: List[Dict] = []

    def F(sev, rule, msg, refs=()):
        out.append({"severity": sev, "rule": rule, "message": msg, "refs": list(refs)})

    w, l = mech["outline_mm"]["size"]
    mw, ml = env.get("max_outline_mm", [1e9, 1e9])
    if (w > mw + 1e-6 or l > ml + 1e-6) and (l > mw + 1e-6 or w > ml + 1e-6):
        F("error", "mech_outline", f"board {w}×{l} mm does not fit the {mw}×{ml} mm space in {env.get('product', 'the product')}")
    pat = env.get("mount_pattern_mm")
    if pat:
        hs = mech.get("mounting_holes", [])
        want = [(sx * pat / 2, sy * pat / 2) for sx in (-1, 1) for sy in (-1, 1)]
        miss = [c for c in want if not any(abs(h["at_mm"][0] - c[0]) < 0.25 and abs(h["at_mm"][1] - c[1]) < 0.25 for h in hs)]
        if miss:
            F("error", "mech_mounting", f"mounting holes do not match the {pat} mm square pattern the product uses "
                                        f"(missing near {miss[:2]}); holes found at {[h['at_mm'] for h in hs][:4]}")
        dmin = env.get("mount_hole_d_mm")
        if dmin and any(h["drill_mm"] + 1e-6 < dmin for h in hs):
            F("error", "mech_mounting", f"mounting holes smaller than the {dmin} mm the product's screws need")
    if env.get("mount_holes_mm"):
        # the product has standoffs at fixed positions (an enclosure built around an earlier version of the board)
        hs = mech.get("mounting_holes", [])
        want = [tuple(x) for x in env["mount_holes_mm"]]
        miss = [c for c in want if not any(abs(h["at_mm"][0] - c[0]) < 0.25 and abs(h["at_mm"][1] - c[1]) < 0.25
                                           for h in hs)]
        extra = [h["at_mm"] for h in hs if not any(abs(h["at_mm"][0] - c[0]) < 0.25 and abs(h["at_mm"][1] - c[1]) < 0.25
                                                   for c in want)]
        if miss or extra:
            F("error", "mech_mounting", f"the enclosure's standoffs are at {want}; the board's holes are at "
                                        f"{[h['at_mm'] for h in hs]}. Rebuild the enclosure (rlcad integrate) or move "
                                        "the holes back")
        else:
            F("info", "mech_mounting", f"{len(want)} holes match the enclosure's standoffs")
    ko = env.get("keepout_height_mm", {})
    for side in ("top", "bottom"):
        lim = ko.get(side)
        if lim is None:
            continue
        tall = [c for c in mech["components"] if c["side"] == side and c["height_mm"] > lim]
        if tall:
            tall.sort(key=lambda c: -c["height_mm"])
            F("error", "mech_height", f"{len(tall)} {side}-side parts are taller than the {lim} mm the product allows: "
                                      + ", ".join(f"{c['ref']} {c['height_mm']} mm" for c in tall[:6]),
              [c["ref"] for c in tall])
        else:
            est = [c["ref"] for c in mech["components"] if c["side"] == side and c["height_source"] == "est"]
            F("info", "mech_height", f"{side} side: tallest part {mech['height_mm'][side]} mm ≤ {lim} mm allowed"
                                     + (f" (heights estimated for {', '.join(est[:5])})" if est else ""))
    reach = set(env.get("reachable_edges", []))
    for req in env.get("required_ports", []):
        cands = [c for c in mech["connectors"] if c["mate"] == req["mate"]]
        if not cands:
            F("error", "mech_port", f"the product expects a {req['mate']} connector ({req.get('why', '')}); the board has none")
            continue
        for c in cands:
            ok_edges = set(req.get("edges") or reach)
            if req.get("via_extension"):
                F("info", "mech_port", f"{c['ref']} ({c['mate']}) is brought out by an extension cable: "
                                       f"{req.get('why', '')}", [c["ref"]])
            elif c["edge"] not in ok_edges:
                F("error", "mech_port", f"{c['ref']} ({c['mate']}) faces the {c['edge']} edge; it must face one of "
                                        f"{sorted(ok_edges)} to be reachable ({req.get('why', '')})", [c["ref"]])
            else:
                F("info", "mech_port", f"{c['ref']} ({c['mate']}) faces {c['edge']}: reachable", [c["ref"]])
    by = {s: sum(1 for f in out if f["severity"] == s) for s in ("error", "warning", "info")}
    return {"summary": by, "findings": out}
