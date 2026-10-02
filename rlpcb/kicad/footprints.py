"""Footprint (.kicad_mod) model."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from .sexpr import Node, parse_file


@dataclass
class Pad:
    number: str
    kind: str  # smd, thru_hole, np_thru_hole, connect
    shape: str
    x: float
    y: float
    w: float
    h: float
    drill: float = 0.0
    layers: List[str] = field(default_factory=list)


@dataclass
class Footprint:
    lib: str
    name: str
    description: str = ""
    tags: str = ""
    attr: str = ""
    pads: List[Pad] = field(default_factory=list)
    courtyard: tuple = (0.0, 0.0, 0.0, 0.0)
    model: str = ""

    @property
    def fpid(self):
        return f"{self.lib}:{self.name}"

    @property
    def pad_numbers(self):
        return sorted({p.number for p in self.pads if p.number}, key=_nat)

    @property
    def size(self):
        x0, y0, x1, y1 = self.courtyard
        return round(x1 - x0, 3), round(y1 - y0, 3)

    @property
    def mount(self):
        kinds = {p.kind for p in self.pads}
        if "thru_hole" in kinds and "smd" in kinds:
            return "mixed"
        if "thru_hole" in kinds:
            return "tht"
        if "smd" in kinds:
            return "smd"
        return self.attr or "other"

    def summary(self):
        w, h = self.size
        pitches = _pitch(self.pads)
        return {
            "footprint": self.fpid,
            "description": self.description,
            "tags": self.tags,
            "mount": self.mount,
            "pad_count": len(self.pad_numbers),
            "courtyard_mm": [w, h],
            "min_pitch_mm": pitches,
            "min_drill_mm": min((p.drill for p in self.pads if p.drill), default=None),
            "3d_model": self.model,
        }


def _pitch(pads):
    pts = [(p.x, p.y) for p in pads if p.kind != "np_thru_hole"]
    best = None
    for i in range(len(pts)):
        for j in range(i + 1, min(len(pts), i + 40)):
            d = ((pts[i][0] - pts[j][0]) ** 2 + (pts[i][1] - pts[j][1]) ** 2) ** 0.5
            if d > 0.05 and (best is None or d < best):
                best = d
    return round(best, 3) if best else None


def _nat(s):
    import re
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def parse_footprint_node(n: Node, lib: str = "") -> Footprint:
    name = str(n.items[1]).split(":")[-1]
    fp = Footprint(lib=lib, name=name, description=str(n.value("descr", "") or ""), tags=str(n.value("tags", "") or ""))
    attr = n.child("attr")
    if attr is not None and len(attr.items) > 1:
        fp.attr = str(attr.items[1])
    xs, ys = [], []
    for pad in n.children("pad"):
        at = pad.xy() or [0, 0]
        sz = pad.xy("size") or [0, 0]
        dr = pad.child("drill")
        drill = 0.0
        if dr is not None:
            nums = [a for a in dr.items[1:] if not isinstance(a, Node) and a != "oval"]
            try:
                drill = float(nums[0]) if nums else 0.0
            except ValueError:
                drill = 0.0
        layers = [str(a) for a in (pad.child("layers").items[1:] if pad.child("layers") is not None else [])]
        fp.pads.append(Pad(str(pad.items[1]), str(pad.items[2]), str(pad.items[3]) if len(pad.items) > 3 else "",
                           at[0], at[1], sz[0], sz[1], drill, layers))
    for tag in ("fp_line", "fp_rect", "fp_poly", "fp_circle"):
        for g in n.children(tag):
            layer = g.value("layer", "")
            if layer not in ("F.CrtYd", "B.CrtYd"):
                continue
            for h in ("start", "end", "center"):
                p = g.xy(h)
                if p:
                    xs.append(p[0])
                    ys.append(p[1])
            pts = g.child("pts")
            if pts is not None:
                for xy in pts.children("xy"):
                    xs.append(float(xy.items[1]))
                    ys.append(float(xy.items[2]))
    if not xs and fp.pads:
        for p in fp.pads:
            xs += [p.x - p.w / 2, p.x + p.w / 2]
            ys += [p.y - p.h / 2, p.y + p.h / 2]
    if xs:
        fp.courtyard = (min(xs), min(ys), max(xs), max(ys))
    m = n.child("model")
    if m is not None:
        fp.model = str(m.items[1])
    return fp


def load_footprint(path: str, lib: Optional[str] = None) -> Footprint:
    lib = lib or os.path.splitext(os.path.basename(os.path.dirname(path)))[0]
    return parse_footprint_node(parse_file(path), lib)
