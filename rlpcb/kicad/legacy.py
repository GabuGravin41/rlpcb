"""Reader for legacy KiCad 4/5 schematics (.sch) and symbol libraries (.lib).

Much of the open-hardware world (VESC, LibreSolar, many robotics/industrial designs)
was drawn in KiCad 4/5. This reader maps those files onto the same model the rest
of RL PCB uses, so connectivity, the reference corpus and verification all work.
Coordinates are converted from mils to mm; symbol orientation matrices are kept exactly.
"""
from __future__ import annotations

import glob
import os
import re
import shlex
from typing import Dict, List, Optional

from .schematic import Label, SchSymbol, Schematic, Sheet, SheetPin, Wire
from .symbols import LibSymbol, Pin

MIL = 0.0254

_ETYPE = {"I": "input", "O": "output", "B": "bidirectional", "T": "tri_state", "P": "passive", "U": "unspecified",
          "W": "power_in", "w": "power_out", "C": "open_collector", "E": "open_emitter", "N": "no_connect"}
_ORIENT_ANGLE = {"R": 0, "U": 90, "L": 180, "D": 270}  # pin points from its end toward...: R = to the right


def _tok(line: str) -> List[str]:
    try:
        return shlex.split(line, posix=True)
    except ValueError:
        return line.split()


def parse_legacy_lib(path: str) -> Dict[str, LibSymbol]:
    """Parse a KiCad legacy .lib into LibSymbols keyed by name (aliases included)."""
    out: Dict[str, LibSymbol] = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    i = 0
    cur: Optional[LibSymbol] = None
    aliases: List[str] = []
    minx = miny = 1e9
    maxx = maxy = -1e9
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("DEF "):
            t = _tok(ln)
            name = t[1].lstrip("~")
            cur = LibSymbol(lib_id=name)
            cur.properties["Reference"] = t[2]
            cur.unit_count = int(t[7]) if len(t) > 7 and t[7].isdigit() else 1
            cur.power = len(t) > 9 and t[9] == "P"
            aliases = []
            minx = miny = 1e9
            maxx = maxy = -1e9
        elif ln.startswith("F1 ") and cur is not None:
            t = _tok(ln)
            cur.properties["Value"] = t[1] if len(t) > 1 else ""
        elif ln.startswith("F2 ") and cur is not None:
            t = _tok(ln)
            cur.properties["Footprint"] = t[1] if len(t) > 1 else ""
        elif ln.startswith("F3 ") and cur is not None:
            t = _tok(ln)
            cur.properties["Datasheet"] = t[1] if len(t) > 1 else ""
        elif ln.startswith("ALIAS ") and cur is not None:
            aliases += ln.split()[1:]
        elif ln.startswith("X ") and cur is not None:
            t = ln.split()
            # X name num posx posy length orient Snum Snom unit convert etype [shape]
            if len(t) >= 12:
                shape = t[12] if len(t) > 12 else ""
                x, y = int(t[3]) * MIL, int(t[4]) * MIL
                p = Pin(number=t[2], name=t[1], etype=_ETYPE.get(t[11], "unspecified"), shape=shape,
                        x=round(x, 4), y=round(y, 4), angle=_ORIENT_ANGLE.get(t[6], 0), length=int(t[5]) * MIL,
                        hidden=shape.startswith("N"), unit=int(t[9]), style=int(t[10]))
                cur.pins.append(p)
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
        elif ln.startswith(("S ", "P ", "C ", "A ")) and cur is not None:
            nums = [int(v) for v in re.findall(r"-?\d+", ln)[:12]]
            if ln.startswith("S ") and len(nums) >= 4:
                for xv, yv in ((nums[0], nums[1]), (nums[2], nums[3])):
                    minx, maxx = min(minx, xv * MIL), max(maxx, xv * MIL)
                    miny, maxy = min(miny, yv * MIL), max(maxy, yv * MIL)
        elif ln.startswith("ENDDEF") and cur is not None:
            if minx <= maxx:
                cur.bbox = (minx, miny, maxx, maxy)
            out[cur.lib_id] = cur
            for a in aliases:
                alias = LibSymbol(lib_id=a, properties=dict(cur.properties, Value=a), pins=cur.pins, power=cur.power,
                                  unit_count=cur.unit_count, bbox=cur.bbox)
                out[a] = alias
            cur = None
        i += 1
    return out


class LegacySchematic(Schematic):
    """A KiCad 4/5 .sch file presented through the modern Schematic interface."""

    _lib_cache: Dict[str, Dict[str, LibSymbol]] = {}

    def __init__(self, path: str, libs: Optional[Dict[str, LibSymbol]] = None):  # noqa: D401 (no super().__init__)
        self.path = os.path.abspath(path)
        self.text = ""
        self.root = None
        self.version = 0
        self.uuid = ""
        self.lib_symbols: Dict[str, LibSymbol] = {}
        self.symbols: List[SchSymbol] = []
        self.wires: List[Wire] = []
        self.junctions = []
        self.no_connects = []
        self.labels: List[Label] = []
        self.sheets: List[Sheet] = []
        self.bus_entries = []
        self.texts: List[str] = []
        self.libs = libs if libs is not None else find_project_libs(self.path)
        self._parse()

    def _parse(self):
        with open(self.path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        i = 0
        n = len(lines)
        while i < n:
            ln = lines[i]
            if ln.startswith("$Comp"):
                j = i + 1
                block = []
                while j < n and not lines[j].startswith("$EndComp"):
                    block.append(lines[j])
                    j += 1
                self._comp(block)
                i = j
            elif ln.startswith("Wire Wire Line") or ln.startswith("Wire Bus Line"):
                v = [int(x) * MIL for x in lines[i + 1].split()[:4]]
                self.wires.append(Wire(round(v[0], 4), round(v[1], 4), round(v[2], 4), round(v[3], 4), bus="Bus" in ln))
                i += 1
            elif ln.startswith("Entry Wire Line") or ln.startswith("Entry Bus Bus"):
                v = [int(x) * MIL for x in lines[i + 1].split()[:4]]
                self.bus_entries.append((round(v[0], 4), round(v[1], 4), round(v[2], 4), round(v[3], 4)))
                i += 1
            elif ln.startswith("Connection "):
                t = ln.split()
                self.junctions.append((round(int(t[2]) * MIL, 4), round(int(t[3]) * MIL, 4)))
            elif ln.startswith("NoConn "):
                t = ln.split()
                self.no_connects.append((round(int(t[2]) * MIL, 4), round(int(t[3]) * MIL, 4)))
            elif ln.startswith("Text "):
                t = ln.split()
                kind = {"Label": "label", "GLabel": "global_label", "HLabel": "hierarchical_label"}.get(t[1])
                text = lines[i + 1] if i + 1 < n else ""
                if kind:
                    self.labels.append(Label(text.strip(), kind, round(int(t[2]) * MIL, 4), round(int(t[3]) * MIL, 4),
                                             {0: 0, 1: 90, 2: 180, 3: 270}.get(int(t[4]) if t[4].isdigit() else 0, 0)))
                else:
                    self.texts.append(text)
                i += 1
            elif ln.startswith("$Sheet"):
                j = i + 1
                block = []
                while j < n and not lines[j].startswith("$EndSheet"):
                    block.append(lines[j])
                    j += 1
                self._sheet(block)
                i = j
            i += 1

    def _comp(self, block: List[str]):
        name = ref = ""
        unit = 1
        x = y = 0.0
        props: Dict[str, str] = {}
        insts = {}
        matrix = None
        ts = ""
        tail_nums = []
        for ln in block:
            s = ln.strip()
            if s.startswith("L "):
                t = s.split()
                name, ref = t[1], t[2] if len(t) > 2 else "?"
            elif s.startswith("U "):
                t = s.split()
                unit = int(t[1]) if t[1].isdigit() else 1
                ts = t[3] if len(t) > 3 else ""
            elif s.startswith("P "):
                t = s.split()
                x, y = int(t[1]) * MIL, int(t[2]) * MIL
            elif s.startswith("F "):
                t = _tok(s)
                idx = int(t[1])
                key = {0: "Reference", 1: "Value", 2: "Footprint", 3: "Datasheet"}.get(idx)
                if key is None and len(t) > 11:
                    key = t[-1]
                if key:
                    props[key] = t[2]
            elif s.startswith("AR "):
                m = re.search(r'Path="([^"]*)"\s+Ref="([^"]*)"\s+Part="(\d+)"', s)
                if m:
                    path = m.group(1)
                    sheet_path = path.rsplit("/", 1)[0] if path.count("/") > 1 else ""
                    insts[sheet_path] = (m.group(2), int(m.group(3)))
            elif re.match(r"^-?\d+\s+-?\d+\s+-?\d+\s+-?\d+$", s):
                matrix = tuple(int(v) for v in s.split())
            else:
                tail_nums.append(s)
        props.setdefault("Reference", ref)
        lib = self._resolve(name)
        lid = name
        if lib is not None:
            self.lib_symbols[lid] = lib
        sym = SchSymbol(lib_id=lid, uuid=ts, x=round(x, 4), y=round(y, 4), angle=0, mirror=None, unit=unit, style=1,
                        properties=props, instances=insts)
        sym.matrix = matrix or (1, 0, 0, -1)  # type: ignore[attr-defined]
        self.symbols.append(sym)

    def _resolve(self, name: str) -> Optional[LibSymbol]:
        for cand in (name, name.replace(":", "_"), name.split(":")[-1]):
            if cand in self.libs:
                return self.libs[cand]
        return None

    def _sheet(self, block: List[str]):
        x = y = w = h = 0.0
        ts = sname = sfile = ""
        pins = []
        for ln in block:
            s = ln.strip()
            if s.startswith("S "):
                t = s.split()
                x, y, w, h = (int(v) * MIL for v in t[1:5])
            elif s.startswith("U "):
                ts = s.split()[1]
            elif s.startswith("F0 "):
                sname = _tok(s)[1]
            elif s.startswith("F1 "):
                sfile = _tok(s)[1]
            elif re.match(r"^F\d+ ", s):
                t = _tok(s)
                # F2 "name" I R x y size
                if len(t) >= 6:
                    pins.append(SheetPin(t[1], t[2], round(int(t[4]) * MIL, 4), round(int(t[5]) * MIL, 4)))
        self.sheets.append(Sheet(sname, sfile, ts, round(x, 4), round(y, 4), round(w, 4), round(h, 4), pins))

    # modern interface overrides
    def lib_for(self, s: SchSymbol):
        return self.lib_symbols.get(s.lib_id)

    def pin_positions(self, s: SchSymbol, unit: Optional[int] = None):
        lib = self.lib_for(s)
        if lib is None:
            return
        a, b, c, d = getattr(s, "matrix", (1, 0, 0, -1))
        u = unit or s.unit
        for p in lib.pins_for_unit(u, s.style):
            yield p, round(s.x + a * p.x + b * p.y, 4), round(s.y + c * p.x + d * p.y, 4)


def find_project_libs(sch_path: str) -> Dict[str, LibSymbol]:
    """Load every .lib next to the schematic (cache and rescue libraries first)."""
    d = os.path.dirname(os.path.abspath(sch_path))
    key = d
    if key in LegacySchematic._lib_cache:
        return LegacySchematic._lib_cache[key]
    libs: Dict[str, LibSymbol] = {}
    files = sorted(glob.glob(os.path.join(d, "*.lib")) + glob.glob(os.path.join(d, "*", "*.lib")),
                   key=lambda p: (0 if "cache" in p else 1 if "rescue" in p else 2, p))
    for f in reversed(files):  # cache wins: loaded last
        try:
            libs.update(parse_legacy_lib(f))
        except Exception:
            continue
    LegacySchematic._lib_cache[key] = libs
    return libs
