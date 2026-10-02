"""Schematic model: symbols, wires, labels, sheets, and hierarchy traversal."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .geometry import key, sym_transform
from .sexpr import Node, parse
from .symbols import LibSymbol, parse_lib_symbol


def _unesc(s: str) -> str:
    if "{" not in s:
        return s
    from .connectivity import unescape_label
    return unescape_label(s)


@dataclass
class SchSymbol:
    lib_id: str
    uuid: str
    x: float
    y: float
    angle: float
    mirror: Optional[str]
    unit: int
    style: int
    properties: Dict[str, str]
    instances: Dict[str, Tuple[str, int]]  # path -> (reference, unit)
    in_bom: bool = True
    on_board: bool = True
    dnp: bool = False
    lib_name: Optional[str] = None  # when the cache entry is renamed (lib_name "X_1")
    pin_uuids: Dict[str, str] = field(default_factory=dict)
    node: Optional[Node] = None

    @property
    def reference(self):
        return self.properties.get("Reference", "?")

    @property
    def value(self):
        return self.properties.get("Value", "")

    @property
    def footprint(self):
        return self.properties.get("Footprint", "")

    def ref_for_path(self, sheet_path: str) -> Tuple[str, int]:
        """Reference/unit for a given sheet instance path ("/uuid/uuid" without root)."""
        if not self.instances:
            return self.reference, self.unit
        best = None
        for p, v in self.instances.items():
            if p == sheet_path or p.endswith(sheet_path) and sheet_path:
                return v
            # root sheet: path is "/<root-uuid>" only
            if sheet_path == "" and p.count("/") == 1:
                best = v
        if best:
            return best
        return next(iter(self.instances.values()))


@dataclass
class Wire:
    x1: float
    y1: float
    x2: float
    y2: float
    uuid: str = ""
    bus: bool = False


@dataclass
class Label:
    text: str
    kind: str  # label | global_label | hierarchical_label | netclass_flag | directive_label
    x: float
    y: float
    angle: float = 0
    shape: str = ""
    uuid: str = ""


@dataclass
class SheetPin:
    name: str
    etype: str
    x: float
    y: float


@dataclass
class Sheet:
    name: str
    file: str
    uuid: str
    x: float
    y: float
    w: float
    h: float
    pins: List[SheetPin] = field(default_factory=list)


class Schematic:
    """One .kicad_sch file (not the hierarchy)."""

    def __init__(self, path: str, text: Optional[str] = None):
        self.path = os.path.abspath(path)
        if text is None:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        self.text = text
        self.root = parse(text)
        if self.root.head != "kicad_sch":
            raise ValueError(f"{path} is not a KiCad schematic (head={self.root.head})")
        self.version = int(self.root.value("version", "0") or 0)
        self.uuid = str(self.root.value("uuid", "") or "")
        self.lib_symbols: Dict[str, LibSymbol] = {}
        self.symbols: List[SchSymbol] = []
        self.wires: List[Wire] = []
        self.junctions: List[Tuple[float, float]] = []
        self.no_connects: List[Tuple[float, float]] = []
        self.labels: List[Label] = []
        self.sheets: List[Sheet] = []
        self.bus_entries: List[Tuple[float, float, float, float]] = []
        self.texts: List[str] = []
        self._load()

    # ------------------------------------------------------------------
    def _load(self):
        ls = self.root.child("lib_symbols")
        if ls is not None:
            for n in ls.children("symbol"):
                s = parse_lib_symbol(n)
                self.lib_symbols[s.lib_id] = s
        for n in self.root.items[1:]:
            if not isinstance(n, Node):
                continue
            h = n.head
            if h == "symbol":
                self.symbols.append(self._parse_symbol(n))
            elif h in ("wire", "bus"):
                pts = n.child("pts")
                xy = [c for c in pts.children("xy")] if pts is not None else []
                for a, b in zip(xy, xy[1:]):
                    self.wires.append(Wire(float(a[1]), float(a[2]), float(b[1]), float(b[2]),
                                           str(n.value("uuid", "")), bus=(h == "bus")))
            elif h == "junction":
                at = n.xy()
                self.junctions.append((at[0], at[1]))
            elif h == "no_connect":
                at = n.xy()
                self.no_connects.append((at[0], at[1]))
            elif h in ("label", "global_label", "hierarchical_label", "directive_label", "netclass_flag"):
                at = n.xy() or [0, 0, 0]
                self.labels.append(Label(_unesc(str(n.items[1])), h, at[0], at[1], at[2] if len(at) > 2 else 0,
                                         str(n.value("shape", "")), str(n.value("uuid", ""))))
            elif h == "sheet":
                self.sheets.append(self._parse_sheet(n))
            elif h == "bus_entry":
                at, sz = n.xy(), n.xy("size")
                self.bus_entries.append((at[0], at[1], at[0] + sz[0], at[1] + sz[1]))
            elif h == "text":
                self.texts.append(str(n.items[1]))

    def _parse_symbol(self, n: Node) -> SchSymbol:
        at = n.xy() or [0, 0, 0]
        props = {}
        for p in n.children("property"):
            props[str(p.items[1])] = str(p.items[2])
        inst = {}
        insts = n.child("instances")
        if insts is not None:
            for proj in insts.children("project"):
                for path in proj.children("path"):
                    inst[str(path.items[1])] = (str(path.value("reference", props.get("Reference", "?"))),
                                                int(path.value("unit", "1") or 1))
        pin_uuids = {}
        for pin in n.children("pin"):
            pin_uuids[str(pin.items[1])] = str(pin.value("uuid", ""))
        style = n.value("body_style") or n.value("convert") or "1"
        return SchSymbol(
            lib_id=str(n.value("lib_id", "")),
            uuid=str(n.value("uuid", "")),
            x=at[0], y=at[1], angle=at[2] if len(at) > 2 else 0,
            mirror=n.value("mirror"),
            unit=int(n.value("unit", "1") or 1),
            style=int(style),
            properties=props,
            instances=inst,
            in_bom=n.value("in_bom", "yes") != "no",
            on_board=n.value("on_board", "yes") != "no",
            dnp=n.value("dnp", "no") == "yes",
            lib_name=n.value("lib_name"),
            pin_uuids=pin_uuids,
            node=n,
        )

    def _parse_sheet(self, n: Node) -> Sheet:
        at, sz = n.xy() or [0, 0], n.xy("size") or [0, 0]
        props = {str(p.items[1]): str(p.items[2]) for p in n.children("property")}
        name = props.get("Sheetname") or props.get("Sheet name") or ""
        file = props.get("Sheetfile") or props.get("Sheet file") or ""
        pins = []
        for p in n.children("pin"):
            pa = p.xy() or [0, 0]
            pins.append(SheetPin(_unesc(str(p.items[1])), str(p.items[2]) if len(p.items) > 2 and not isinstance(p.items[2], Node) else "", pa[0], pa[1]))
        return Sheet(name, file, str(n.value("uuid", "")), at[0], at[1], sz[0], sz[1], pins)

    # ------------------------------------------------------------------
    def lib_for(self, s: SchSymbol) -> Optional[LibSymbol]:
        if s.lib_name:
            ln = str(s.lib_name)
            hit = self.lib_symbols.get(ln)
            if hit is None and ":" in s.lib_id:
                hit = self.lib_symbols.get(s.lib_id.split(":", 1)[0] + ":" + ln)
            if hit is not None:
                return hit
        return self.lib_symbols.get(s.lib_id)

    def pin_positions(self, s: SchSymbol, unit: Optional[int] = None):
        """Yield (Pin, abs_x, abs_y) for the symbol's pins in its unit."""
        lib = self.lib_for(s)
        if lib is None:
            return
        u = unit or s.unit
        for p in lib.pins_for_unit(u, s.style):
            dx, dy = sym_transform(p.x, p.y, s.angle, s.mirror)
            yield p, round(s.x + dx, 4), round(s.y + dy, 4)

    def symbol_bbox(self, s: SchSymbol):
        lib = self.lib_for(s)
        if lib is None:
            return (s.x - 2.54, s.y - 2.54, s.x + 2.54, s.y + 2.54)
        x0, y0, x1, y1 = lib.bbox
        pts = [sym_transform(px, py, s.angle, s.mirror) for px, py in ((x0, y0), (x1, y1), (x0, y1), (x1, y0))]
        xs = [s.x + p[0] for p in pts]
        ys = [s.y + p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))


@dataclass
class SheetInstance:
    sch: Schematic
    path: str  # "/uuid/uuid" of sheet symbols from root ("" for root)
    name_path: str  # "/Power/Buck/" human path
    parent: Optional["SheetInstance"] = None
    sheet: Optional[Sheet] = None  # the sheet symbol in the parent


class Hierarchy:
    """A full design: the root schematic and every sheet instance."""

    def __init__(self, root_path: str):
        root_path = os.path.abspath(root_path)
        if root_path.endswith(".kicad_pro"):
            root_path = root_path[:-len(".kicad_pro")] + ".kicad_sch"
            if not os.path.exists(root_path) and os.path.exists(root_path[:-len(".kicad_sch")] + ".sch"):
                root_path = root_path[:-len(".kicad_sch")] + ".sch"
        elif root_path.endswith(".pro"):
            root_path = root_path[:-len(".pro")] + ".sch"
        self.root_path = root_path
        self.project_dir = os.path.dirname(root_path)
        self.project_name = os.path.splitext(os.path.basename(root_path))[0]
        self._cache: Dict[str, Schematic] = {}
        self.instances: List[SheetInstance] = []
        self.errors: List[str] = []
        root = self.load(root_path)
        self.root = root
        self._walk(SheetInstance(root, "", "/"), 0)

    def load(self, path: str) -> Schematic:
        path = os.path.abspath(path)
        if path not in self._cache:
            if path.endswith(".sch"):
                from .legacy import LegacySchematic
                self._cache[path] = LegacySchematic(path)
            else:
                self._cache[path] = Schematic(path)
        return self._cache[path]

    def bus_aliases(self) -> Dict[str, List[str]]:
        """Bus aliases from all sheets (KiCad <= 8) and the .kicad_pro (KiCad 9+)."""
        out: Dict[str, List[str]] = {}
        for sch in self._cache.values():
            if sch.root is None:
                continue
            for ba in sch.root.children("bus_alias"):
                mem = ba.child("members")
                out[str(ba.items[1])] = [str(m) for m in mem.items[1:]] if mem is not None else []
        pro = os.path.join(self.project_dir, self.project_name + ".kicad_pro")
        if os.path.exists(pro):
            try:
                import json
                with open(pro, encoding="utf-8") as f:
                    d = json.load(f)
                ba = (d.get("schematic") or {}).get("bus_aliases") or {}
                if isinstance(ba, dict):
                    for k, v in ba.items():
                        out.setdefault(k, list(v))
                elif isinstance(ba, list):
                    for e in ba:
                        if isinstance(e, dict) and "name" in e:
                            out.setdefault(e["name"], list(e.get("members", [])))
            except Exception:
                pass
        return out

    @property
    def files(self) -> List[Schematic]:
        return list(self._cache.values())

    def _walk(self, inst: SheetInstance, depth: int):
        self.instances.append(inst)
        if depth > 32:
            self.errors.append("Hierarchy deeper than 32 levels (recursive sheet?)")
            return
        base = os.path.dirname(inst.sch.path)
        for sh in inst.sch.sheets:
            p = os.path.join(base, sh.file.replace("\\", "/"))
            if not os.path.exists(p):
                self.errors.append(f"Missing sheet file {sh.file} (sheet '{sh.name}' in {os.path.basename(inst.sch.path)})")
                continue
            try:
                child = self.load(p)
            except Exception as e:  # noqa
                self.errors.append(f"Failed to parse {p}: {e}")
                continue
            self._walk(SheetInstance(child, f"{inst.path}/{sh.uuid}", f"{inst.name_path}{sh.name}/", inst, sh), depth + 1)

    def iter_symbols(self):
        """Yield (SheetInstance, SchSymbol, reference, unit) for every placed symbol instance."""
        for inst in self.instances:
            for s in inst.sch.symbols:
                ref, unit = s.ref_for_path(inst.path)
                yield inst, s, ref, unit

    def components(self, include_power=False) -> Dict[str, dict]:
        """Aggregate components by reference (multi-unit symbols merged)."""
        out: Dict[str, dict] = {}
        for inst, s, ref, unit in self.iter_symbols():
            lib = inst.sch.lib_for(s)
            is_power = (lib.power if lib else False) or ref.startswith("#")
            if is_power and not include_power:
                continue
            c = out.setdefault(ref, {
                "reference": ref, "value": s.value, "lib_id": s.lib_id, "footprint": s.footprint,
                "datasheet": s.properties.get("Datasheet", ""), "units": [], "sheet": inst.name_path,
                "dnp": s.dnp, "in_bom": s.in_bom, "on_board": s.on_board,
                "fields": {k: v for k, v in s.properties.items() if k not in ("Reference", "Value", "Footprint", "Datasheet") and v},
            })
            c["units"].append(unit)
        return out
