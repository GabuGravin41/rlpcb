"""Symbol library model (.kicad_sym files and schematic lib_symbols caches)."""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .sexpr import Node, parse_file, QStr

_unit_re = re.compile(r"_(\d+)_(\d+)$")


@dataclass
class Pin:
    number: str
    name: str
    etype: str  # input, output, bidirectional, tri_state, passive, free, unspecified, power_in, power_out, open_collector, open_emitter, no_connect
    shape: str
    x: float
    y: float
    angle: float
    length: float
    hidden: bool = False
    unit: int = 0  # 0 = common to all units
    style: int = 0  # body style (De Morgan); 0 = common
    alternates: List[str] = field(default_factory=list)

    def to_dict(self):
        d = {"number": self.number, "name": self.name, "type": self.etype}
        if self.unit:
            d["unit"] = self.unit
        if self.hidden:
            d["hidden"] = True
        if self.alternates:
            d["alternates"] = self.alternates
        return d


@dataclass
class LibSymbol:
    lib_id: str  # "Lib:Name" or bare "Name" inside a .kicad_sym
    node: Optional[Node] = None
    properties: Dict[str, str] = field(default_factory=dict)
    pins: List[Pin] = field(default_factory=list)
    extends: Optional[str] = None
    power: bool = False
    power_scope: str = "global"
    unit_count: int = 1
    has_demorgan: bool = False
    in_bom: bool = True
    on_board: bool = True
    unit_names: Dict[int, str] = field(default_factory=dict)
    bbox: tuple = (0.0, 0.0, 0.0, 0.0)  # library coords, min_x, min_y, max_x, max_y

    @property
    def name(self):
        return self.lib_id.split(":", 1)[-1]

    @property
    def reference_prefix(self):
        return self.properties.get("Reference", "U").rstrip("?")

    @property
    def description(self):
        return self.properties.get("Description") or self.properties.get("ki_description", "")

    @property
    def keywords(self):
        return self.properties.get("ki_keywords", "")

    @property
    def fp_filters(self):
        return self.properties.get("ki_fp_filters", "")

    def pins_for_unit(self, unit: int, style: int = 1) -> List[Pin]:
        return [p for p in self.pins if p.unit in (0, unit) and p.style in (0, style)]

    def summary(self, with_pins=True, max_pins=400):
        d = {
            "lib_id": self.lib_id,
            "value": self.properties.get("Value", ""),
            "reference_prefix": self.reference_prefix,
            "description": self.description,
            "keywords": self.keywords,
            "footprint": self.properties.get("Footprint", ""),
            "footprint_filters": self.fp_filters,
            "datasheet": self.properties.get("Datasheet", ""),
            "units": self.unit_count,
            "power_symbol": self.power,
        }
        if self.extends:
            d["extends"] = self.extends
        if with_pins:
            pins = sorted({(p.number, p.name, p.etype, p.unit, p.hidden) for p in self.pins},
                          key=lambda t: (t[3], _natkey(t[0])))
            d["pin_count"] = len({p[0] for p in pins})
            d["pins"] = [
                {"number": n, "name": nm, "type": t, **({"unit": u} if u else {}), **({"hidden": True} if h else {})}
                for n, nm, t, u, h in pins[:max_pins]
            ]
        return d


def _natkey(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def parse_lib_symbol(node: Node, lib_prefix: str = "") -> LibSymbol:
    name = str(node.items[1])
    lib_id = f"{lib_prefix}:{name}" if lib_prefix and ":" not in name else name
    sym = LibSymbol(lib_id=lib_id, node=node)
    for p in node.children("property"):
        if len(p.items) >= 3:
            sym.properties[str(p.items[1])] = str(p.items[2])
    ext = node.child("extends")
    if ext is not None:
        sym.extends = str(ext.items[1])
    pw = node.child("power")
    sym.power = pw is not None or "power" in [a for a in node.items if not isinstance(a, Node)]
    sym.power_scope = str(pw.items[1]) if pw is not None and len(pw.items) > 1 else "global"  # KiCad 10: (power local)
    inb = node.value("in_bom")
    sym.in_bom = inb != "no"
    onb = node.value("on_board")
    sym.on_board = onb != "no"
    units = set()
    minx = miny = 1e9
    maxx = maxy = -1e9
    for sub in node.children("symbol"):
        sname = str(sub.items[1])
        m = _unit_re.search(sname)
        u, s = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        if u:
            units.add(u)
        if s == 2:
            sym.has_demorgan = True
        un = sub.child("unit_name")
        if un is not None and u:
            sym.unit_names[u] = str(un.items[1])
        for pin in sub.children("pin"):
            at = pin.xy("at") or [0, 0, 0]
            nm = pin.child("name")
            nb = pin.child("number")
            atoms = pin.atoms()
            p = Pin(
                number=str(nb.items[1]) if nb is not None else "",
                name=str(nm.items[1]) if nm is not None else "",
                etype=str(atoms[0]) if atoms else "passive",
                shape=str(atoms[1]) if len(atoms) > 1 else "line",
                x=at[0], y=at[1], angle=at[2] if len(at) > 2 else 0,
                length=pin.fvalue("length", 2.54),
                hidden=pin.has_flag("hide"),
                unit=u, style=s,
                alternates=[str(a.items[1]) for a in pin.children("alternate")],
            )
            sym.pins.append(p)
            minx, maxx = min(minx, p.x), max(maxx, p.x)
            miny, maxy = min(miny, p.y), max(maxy, p.y)
        for shape in ("rectangle",):
            for r in sub.children(shape):
                st, en = r.xy("start"), r.xy("end")
                if st and en:
                    minx, maxx = min(minx, st[0], en[0]), max(maxx, st[0], en[0])
                    miny, maxy = min(miny, st[1], en[1]), max(maxy, st[1], en[1])
        for pl in sub.children("polyline"):
            pts = pl.child("pts")
            if pts is not None:
                for xy in pts.children("xy"):
                    x, y = float(xy.items[1]), float(xy.items[2])
                    minx, maxx = min(minx, x), max(maxx, x)
                    miny, maxy = min(miny, y), max(maxy, y)
    if minx <= maxx:
        sym.bbox = (minx, miny, maxx, maxy)
    sym.unit_count = max(units) if units else 1
    return sym


class SymbolLibrary:
    """A .kicad_sym file."""

    def __init__(self, path: str, nickname: Optional[str] = None):
        self.path = path
        self.nickname = nickname or os.path.splitext(os.path.basename(path.rstrip("/\\")))[0]
        self.symbols: Dict[str, LibSymbol] = {}
        # KiCad 10 ".kicad_symdir" libraries are folders with one .kicad_sym per symbol
        files = sorted(glob.glob(os.path.join(path, "*.kicad_sym"))) if os.path.isdir(path) else [path]
        self.root = None
        for f in files:
            root = parse_file(f)
            self.root = self.root or root
            for n in root.children("symbol"):
                s = parse_lib_symbol(n, self.nickname)
                self.symbols[s.name] = s
        for s in self.symbols.values():
            self._resolve(s)

    def _resolve(self, s: LibSymbol, depth=0):
        """Inherit pins/graphics/properties from parent for derived symbols."""
        if not s.extends or depth > 8:
            return
        parent = self.symbols.get(s.extends)
        if parent is None:
            return
        self._resolve(parent, depth + 1)
        if not s.pins:
            s.pins = parent.pins
            s.unit_count = parent.unit_count
            s.bbox = parent.bbox
            s.has_demorgan = parent.has_demorgan
            s.unit_names = parent.unit_names
        for k, v in parent.properties.items():
            s.properties.setdefault(k, v)
        s.power = s.power or parent.power

    def flattened_node(self, name: str) -> Node:
        """Return a standalone symbol node (derived symbols merged with their parent),
        suitable for embedding in a schematic's lib_symbols with a 'Lib:Name' id."""
        sym = self.symbols[name]
        return flatten_symbol_node(sym, self.symbols, self.nickname)


def flatten_symbol_node(sym: LibSymbol, table: Dict[str, LibSymbol], nickname: str) -> Node:
    from copy import deepcopy

    node = deepcopy(sym.node)
    if sym.extends and sym.extends in table:
        parent = table[sym.extends]
        pnode = flatten_symbol_node(parent, table, nickname)
        # child properties override parent's; keep parent's graphics/pins & flags
        child_props = {str(p.items[1]): p for p in node.children("property")}
        new_items = [node.items[0], QStr(f"{nickname}:{sym.name}")]
        seen_props = set()
        for it in pnode.items[2:]:
            if isinstance(it, Node) and it.head == "property":
                k = str(it.items[1])
                seen_props.add(k)
                new_items.append(child_props.get(k, it))
            elif isinstance(it, Node) and it.head == "symbol":
                sub = deepcopy(it)
                sub.items[1] = QStr(_unit_re.sub(lambda m: f"_{m.group(1)}_{m.group(2)}", str(sub.items[1])).replace(parent.name, sym.name, 1))
                new_items.append(sub)
            else:
                new_items.append(it)
        # insert remaining child-only properties after the last property
        extra = [p for k, p in child_props.items() if k not in seen_props]
        if extra:
            idx = max((i for i, it in enumerate(new_items) if isinstance(it, Node) and it.head == "property"), default=1) + 1
            new_items[idx:idx] = extra
        node.items = new_items
        return node
    node.items[1] = QStr(f"{nickname}:{sym.name}")
    return node
