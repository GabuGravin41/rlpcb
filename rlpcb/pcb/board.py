"""PCB (.kicad_pcb) model: layers, stackup, footprints with absolute pad positions, tracks, vias, zones, outline."""
from __future__ import annotations

import math
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..kicad.sexpr import Node, parse


def rot(x: float, y: float, deg: float) -> Tuple[float, float]:
    """Rotate as KiCad does on a Y-down board: positive angle = counter-clockwise on screen."""
    if not deg:
        return x, y
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return x * c + y * s, -x * s + y * c


@dataclass
class BPad:
    number: str
    kind: str
    shape: str
    x: float
    y: float
    w: float
    h: float
    angle: float
    net: str
    layers: List[str]
    drill: float = 0.0
    pinfunction: str = ""
    pintype: str = ""


@dataclass
class BFootprint:
    ref: str
    value: str
    fpid: str
    x: float
    y: float
    angle: float
    layer: str
    pads: List[BPad] = field(default_factory=list)
    uuid: str = ""
    locked: bool = False
    dnp: bool = False
    courtyard: Tuple[float, float, float, float] = (0, 0, 0, 0)  # absolute bbox
    sheet: str = ""
    node: Optional[Node] = None

    def to_dict(self):
        return {"ref": self.ref, "value": self.value, "footprint": self.fpid, "at_mm": [round(self.x, 3), round(self.y, 3)],
                "rotation": self.angle, "side": "top" if self.layer.startswith("F") else "bottom",
                "size_mm": [round(self.courtyard[2] - self.courtyard[0], 2), round(self.courtyard[3] - self.courtyard[1], 2)],
                "locked": self.locked, "sheet": self.sheet}


@dataclass
class Track:
    x1: float
    y1: float
    x2: float
    y2: float
    width: float
    layer: str
    net: str


@dataclass
class Via:
    x: float
    y: float
    size: float
    drill: float
    net: str
    layers: List[str]
    kind: str = "through"


class Board:
    def __init__(self, path: str, text: Optional[str] = None):
        self.path = os.path.abspath(path)
        if text is None:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        self.text = text
        self.root = parse(text)
        if self.root.head != "kicad_pcb":
            raise ValueError(f"{path} is not a KiCad board")
        self.version = int(self.root.value("version", "0") or 0)
        self.net_names: Dict[str, str] = {}
        self.layers: List[dict] = []
        self.footprints: List[BFootprint] = []
        self.tracks: List[Track] = []
        self.vias: List[Via] = []
        self.zones: List[dict] = []
        self.outline: List[Tuple[float, float, float, float]] = []
        self.stackup: List[dict] = []
        self.thickness = 1.6
        self._load()

    def _net(self, n: Optional[Node]) -> str:
        if n is None or len(n.items) < 2:
            return ""
        if len(n.items) >= 3:
            return str(n.items[2])
        v = str(n.items[1])
        return self.net_names.get(v, v)

    def _load(self):
        for n in self.root.children("net"):
            if len(n.items) >= 3:
                self.net_names[str(n.items[1])] = str(n.items[2])
        ly = self.root.child("layers")
        if ly is not None:
            for l in ly.children():
                self.layers.append({"id": str(l.items[0]), "name": str(l.items[1]), "type": str(l.items[2]) if len(l.items) > 2 else ""})
        gen = self.root.child("general")
        if gen is not None:
            self.thickness = gen.fvalue("thickness", 1.6)
        setup = self.root.child("setup")
        if setup is not None:
            st = setup.child("stackup")
            if st is not None:
                for lay in st.children("layer"):
                    self.stackup.append({"name": str(lay.items[1]), "type": str(lay.value("type", "")),
                                         "thickness_mm": lay.fvalue("thickness", 0.0) if lay.child("thickness") is not None else None,
                                         "material": str(lay.value("material", "") or ""),
                                         "epsilon_r": lay.fvalue("epsilon_r", 0.0) or None})
        for n in self.root.items[1:]:
            if not isinstance(n, Node):
                continue
            h = n.head
            if h in ("footprint", "module"):
                self.footprints.append(self._fp(n))
            elif h == "segment" or h == "arc":
                s, e = n.xy("start"), n.xy("end")
                if s and e:
                    self.tracks.append(Track(s[0], s[1], e[0], e[1], n.fvalue("width", 0.2), str(n.value("layer", "")), self._net(n.child("net"))))
            elif h == "via":
                at = n.xy()
                lays = n.child("layers")
                kind = "through"
                for a in n.atoms():
                    if a in ("blind", "micro", "buried"):
                        kind = a
                self.vias.append(Via(at[0], at[1], n.fvalue("size", 0.6), n.fvalue("drill", 0.3), self._net(n.child("net")),
                                     [str(x) for x in lays.items[1:]] if lays is not None else [], kind))
            elif h == "zone":
                lay = n.child("layer") or n.child("layers")
                pts = []
                poly = n.child("polygon")
                if poly is not None and poly.child("pts") is not None:
                    pts = [(float(p.items[1]), float(p.items[2])) for p in poly.child("pts").children("xy")]
                self.zones.append({"net": self._net(n.child("net")) or str(n.value("net_name", "") or ""),
                                   "layers": [str(x) for x in lay.items[1:]] if lay is not None else [],
                                   "priority": int(n.value("priority", "0") or 0), "points": len(pts),
                                   "bbox": _bbox(pts) if pts else None})
            elif h in ("gr_line", "gr_rect", "gr_arc", "gr_circle", "gr_poly"):
                if n.value("layer") == "Edge.Cuts":
                    pts = [n.xy(k) for k in ("start", "end", "mid", "center") if n.xy(k)]
                    pl = n.child("pts")
                    if pl is not None:
                        pts += [[float(p.items[1]), float(p.items[2])] for p in pl.children("xy")]
                    if h == "gr_circle" and n.xy("center") and n.xy("end"):
                        c, e = n.xy("center"), n.xy("end")
                        r = math.hypot(e[0] - c[0], e[1] - c[1])
                        pts += [[c[0] - r, c[1] - r], [c[0] + r, c[1] + r]]
                    if pts:
                        xs = [p[0] for p in pts]
                        ys = [p[1] for p in pts]
                        self.outline.append((min(xs), min(ys), max(xs), max(ys)))

    def _fp(self, n: Node) -> BFootprint:
        at = n.xy() or [0, 0, 0]
        x, y, a = at[0], at[1], at[2] if len(at) > 2 else 0.0
        props = {str(p.items[1]): str(p.items[2]) for p in n.children("property") if len(p.items) > 2}
        for t in n.children("fp_text"):
            if len(t.items) > 2 and str(t.items[1]) in ("reference", "value"):
                props.setdefault("Reference" if t.items[1] == "reference" else "Value", str(t.items[2]))
        fp = BFootprint(ref=props.get("Reference", "?"), value=props.get("Value", ""), fpid=str(n.items[1]),
                        x=x, y=y, angle=a, layer=str(n.value("layer", "F.Cu")), uuid=str(n.value("uuid", "") or n.value("tstamp", "") or ""),
                        locked=("locked" in n.atoms()) or n.child("locked") is not None and n.value("locked") != "no",
                        dnp=n.child("attr") is not None and "dnp" in n.child("attr").atoms(),
                        sheet=str(n.value("sheetname", "") or props.get("Sheetname", "") or ""), node=n)
        xs, ys = [], []
        for pad in n.children("pad"):
            pa = pad.xy() or [0, 0, 0]
            px, py = rot(pa[0], pa[1], a)
            sz = pad.xy("size") or [0, 0]
            dr = pad.child("drill")
            drill = 0.0
            if dr is not None:
                nums = [v for v in dr.items[1:] if not isinstance(v, Node) and v != "oval"]
                try:
                    drill = float(nums[0]) if nums else 0.0
                except ValueError:
                    pass
            lays = pad.child("layers")
            fp.pads.append(BPad(str(pad.items[1]), str(pad.items[2]), str(pad.items[3]) if len(pad.items) > 3 else "",
                                round(x + px, 4), round(y + py, 4), sz[0], sz[1], pa[2] if len(pa) > 2 else a,
                                self._net(pad.child("net")), [str(v) for v in lays.items[1:]] if lays is not None else [],
                                drill, str(pad.value("pinfunction", "") or ""), str(pad.value("pintype", "") or "")))
        for tag in ("fp_line", "fp_rect", "fp_poly", "fp_circle", "fp_arc"):
            for g in n.children(tag):
                if g.value("layer", "") not in ("F.CrtYd", "B.CrtYd"):
                    continue
                pts = [g.xy(k) for k in ("start", "end", "mid") if g.xy(k)]
                if tag == "fp_circle" and g.xy("center") and g.xy("end"):
                    (cx, cy), (ex, ey) = g.xy("center"), g.xy("end")
                    r_ = math.hypot(ex - cx, ey - cy)
                    pts = [[cx - r_, cy - r_], [cx + r_, cy + r_], [cx - r_, cy + r_], [cx + r_, cy - r_]]
                if g.child("pts") is not None:
                    pts += [[float(p.items[1]), float(p.items[2])] for p in g.child("pts").children("xy")]
                for p in pts:
                    rx, ry = rot(p[0], p[1], a)
                    xs.append(x + rx)
                    ys.append(y + ry)
        if not xs:
            for p in fp.pads:
                xs += [p.x - max(p.w, p.h) / 2, p.x + max(p.w, p.h) / 2]
                ys += [p.y - max(p.w, p.h) / 2, p.y + max(p.w, p.h) / 2]
        if not xs:
            xs, ys = [x - 0.5, x + 0.5], [y - 0.5, y + 0.5]
        fp.courtyard = (min(xs), min(ys), max(xs), max(ys))
        return fp

    # ------------------------------------------------------------ queries
    @property
    def copper_layers(self) -> List[str]:
        return [l["name"] for l in self.layers if l["name"].endswith(".Cu")]

    def board_bbox(self):
        if self.outline:
            return (min(o[0] for o in self.outline), min(o[1] for o in self.outline),
                    max(o[2] for o in self.outline), max(o[3] for o in self.outline))
        if self.footprints:
            return (min(f.courtyard[0] for f in self.footprints), min(f.courtyard[1] for f in self.footprints),
                    max(f.courtyard[2] for f in self.footprints), max(f.courtyard[3] for f in self.footprints))
        return (0, 0, 0, 0)

    def fp(self, ref: str) -> Optional[BFootprint]:
        for f in self.footprints:
            if f.ref == ref:
                return f
        return None

    def net_pads(self) -> Dict[str, List[Tuple[str, BPad]]]:
        out = defaultdict(list)
        for f in self.footprints:
            for p in f.pads:
                if p.net:
                    out[p.net].append((f.ref, p))
        return out

    def overview(self) -> dict:
        x0, y0, x1, y1 = self.board_bbox()
        nets = self.net_pads()
        routed = self.routing_status()
        top = sum(1 for f in self.footprints if f.layer.startswith("F"))
        return {
            "file": self.path, "format_version": self.version,
            "size_mm": [round(x1 - x0, 2), round(y1 - y0, 2)], "has_outline": bool(self.outline),
            "copper_layers": self.copper_layers, "thickness_mm": self.thickness,
            "stackup": self.stackup,
            "footprints": len(self.footprints), "top_side": top, "bottom_side": len(self.footprints) - top,
            "nets_with_pads": len(nets), "tracks": len(self.tracks), "vias": len(self.vias), "zones": len(self.zones),
            "zone_nets": sorted({z["net"] for z in self.zones if z["net"]}),
            "routing": routed,
        }

    def routing_status(self) -> dict:
        """Approximate unrouted connections: union pads joined by copper (tracks, vias, zones by bbox)."""
        from ..kicad.connectivity import DSU

        dsu = DSU()
        pads = []
        for f in self.footprints:
            for i, p in enumerate(f.pads):
                if p.net:
                    pid = f"{f.ref}.{p.number}.{i}"
                    pads.append((pid, p))
                    dsu.find(pid)
        # tracks: connect items that share endpoints or touch pads (within pad half-size)
        pts = defaultdict(list)
        for i, t in enumerate(self.tracks):
            tid = f"t{i}"
            dsu.find(tid)
            pts[(round(t.x1, 3), round(t.y1, 3), t.net)].append(tid)
            pts[(round(t.x2, 3), round(t.y2, 3), t.net)].append(tid)
        for i, v in enumerate(self.vias):
            vid = f"v{i}"
            pts[(round(v.x, 3), round(v.y, 3), v.net)].append(vid)
        for items in pts.values():
            for it in items[1:]:
                dsu.union(items[0], it)
        # track ends inside pads
        by_net_pads = defaultdict(list)
        for pid, p in pads:
            by_net_pads[p.net].append((pid, p))
        for (x, y, net), items in pts.items():
            for pid, p in by_net_pads.get(net, []):
                if abs(x - p.x) <= max(p.w, p.h) / 2 + 0.01 and abs(y - p.y) <= max(p.w, p.h) / 2 + 0.01:
                    dsu.union(items[0], pid)
        # zones: every pad of the zone net inside the zone bbox is considered connected (filled-zone approximation)
        for zi, z in enumerate(self.zones):
            if not z["net"] or not z["bbox"]:
                continue
            zid = f"z{zi}"
            bx0, by0, bx1, by1 = z["bbox"]
            for pid, p in by_net_pads.get(z["net"], []):
                if bx0 <= p.x <= bx1 and by0 <= p.y <= by1:
                    dsu.union(zid, pid)
            for (x, y, net), items in pts.items():
                if net == z["net"] and bx0 <= x <= bx1 and by0 <= y <= by1:
                    dsu.union(zid, items[0])
        unrouted = {}
        total_links = 0
        for net, plist in by_net_pads.items():
            groups = {dsu.find(pid) for pid, _ in plist}
            links = len(plist) - 1
            total_links += max(0, links)
            if len(groups) > 1:
                unrouted[net] = len(groups) - 1
        missing = sum(unrouted.values())
        return {"connections": total_links, "unrouted_connections_approx": missing,
                "percent_routed_approx": round(100 * (1 - missing / total_links), 1) if total_links else 100.0,
                "nets_incomplete": len(unrouted),
                "worst_nets": sorted(unrouted.items(), key=lambda kv: -kv[1])[:25],
                "note": "Estimate from track endpoints/zone extents; run DRC for the exact unconnected list."}


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))
