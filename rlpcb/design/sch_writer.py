"""Place symbols into a KiCad schematic — never wires.

Two delivery modes:
  * ``file``: splice new symbol blocks (and their lib_symbols cache entries)
    into the .kicad_sch text. The rest of the file is left byte-for-byte
    untouched and a timestamped backup is written first. Only safe while the
    schematic is NOT open in the editor (KiCad would overwrite it on save).
  * ``clipboard``: produce the exact text KiCad puts on the clipboard when you
    copy symbols. Paste it into the open schematic editor with Ctrl+V and the
    parts arrive on the cursor, correctly annotated, with footprints set.

Optionally (``labels=True``) a local net label can be dropped exactly on the
end of each pin. Labels are anchored mathematically at the pin's connection
point, so they are real connections — unlike free-hand wires.
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import uuid as uuidlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..kicad.geometry import SCH_GRID, snap, sym_transform
from ..kicad.schematic import Hierarchy, Schematic
from ..kicad.sexpr import Node, QStr, dump, parse
from ..kicad.symbols import LibSymbol, SymbolLibrary, parse_lib_symbol

PAPER = {"A5": (210, 148), "A4": (297, 210), "A3": (420, 297), "A2": (594, 420), "A1": (841, 594),
         "A0": (1189, 841), "A": (279.4, 215.9), "B": (431.8, 279.4), "C": (558.8, 431.8),
         "D": (863.6, 558.8), "E": (1117.6, 863.6), "USLetter": (279.4, 215.9), "USLegal": (355.6, 215.9)}

V8 = 20231120  # KiCad 8 format: quoted uuids, (hide yes), exclude_from_sim
V10_TILDE = 20250318  # from here on "~" is a literal string, empty fields are written as ""


def new_uuid() -> str:
    return str(uuidlib.uuid4())


def lock_file_for(path: str) -> Optional[str]:
    """KiCad writes ~<name>.lck (7+) next to files open in an editor."""
    d, b = os.path.split(path)
    for cand in (f"~{b}.lck", f"~{os.path.splitext(b)[0]}.lck", f".~lock.{b}#"):
        p = os.path.join(d, cand)
        if os.path.exists(p):
            return p
    return None


def backup(path: str) -> str:
    d = os.path.join(os.path.dirname(path), ".rlpcb", "backups")
    os.makedirs(d, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(d, f"{os.path.basename(path)}.{stamp}.bak")
    shutil.copy2(path, dst)
    return dst


@dataclass
class Placement:
    ref: str
    lib_id: str
    value: str
    footprint: str
    x: float
    y: float
    angle: float = 0
    mirror: Optional[str] = None
    unit: int = 1
    fields: Optional[Dict[str, str]] = None
    dnp: bool = False


class SymbolSource:
    """Finds library symbols by lib_id: from the schematic cache, a library index, or .kicad_sym files."""

    def __init__(self, index=None, extra_libs: Optional[Dict[str, str]] = None):
        self.index = index
        self.extra = extra_libs or {}
        self._libs: Dict[str, SymbolLibrary] = {}

    def library(self, nickname: str) -> Optional[SymbolLibrary]:
        if nickname in self._libs:
            return self._libs[nickname]
        path = self.extra.get(nickname)
        if not path and self.index is not None:
            row = self.index.db.execute("SELECT path FROM symbols WHERE lib=? LIMIT 1", (nickname,)).fetchone()
            path = row["path"] if row else None
        if not path or not os.path.exists(path):
            return None
        lib = SymbolLibrary(path, nickname)
        self._libs[nickname] = lib
        return lib

    def get(self, lib_id: str) -> Tuple[Optional[LibSymbol], Optional[Node]]:
        if ":" not in lib_id:
            return None, None
        nick, name = lib_id.split(":", 1)
        lib = self.library(nick)
        if lib is None or name not in lib.symbols:
            return None, None
        node = lib.flattened_node(name)
        sym = parse_lib_symbol(node)
        return sym, node


# ---------------------------------------------------------------------------
def _uuid_atom(u: str, version: int):
    return QStr(u) if version >= V8 else u


def _effects_hidden(effects: Optional[Node], hide: bool, version: int) -> list:
    """Copy an (effects ...) node and set hidden state in the right dialect."""
    font = ["font", ["size", 1.27, 1.27]]
    items = [x for x in (effects.items[1:] if effects is not None else [font])
             if not (isinstance(x, Node) and x.head == "hide") and x != "hide"]
    items = [_to_list(x) for x in items]
    if hide:
        items.append(["hide", "yes"] if version >= V8 else "hide")
    return ["effects", *items]


def _strip_justify(eff: Node) -> Node:
    return Node([x for x in eff.items if not (isinstance(x, Node) and x.head == "justify")])


def _to_list(x):
    if isinstance(x, Node):
        return [_to_list(i) for i in x.items]
    return x


def build_symbol_node(p: Placement, lib: LibSymbol, lib_node: Node, project: str, instance_paths: List[str],
                      version: int) -> list:
    """Return an s-expression (as nested lists) for a placed symbol instance."""
    u = new_uuid()
    items: list = ["symbol", ["lib_id", QStr(p.lib_id)], ["at", p.x, p.y, int(p.angle)]]
    if p.mirror in ("x", "y"):
        items.append(["mirror", p.mirror])
    items.append(["unit", p.unit])
    if version >= V8:
        items.append(["exclude_from_sim", "no"])
    items += [["in_bom", "yes" if lib.in_bom else "no"], ["on_board", "yes" if lib.on_board else "no"],
              ["dnp", "yes" if p.dnp else "no"]]
    items.append(["uuid", _uuid_atom(u, version)])
    values = {"Reference": p.ref, "Value": p.value or lib.properties.get("Value", ""),
              "Footprint": p.footprint or lib.properties.get("Footprint", ""),
              "Datasheet": lib.properties.get("Datasheet", "~") or "~"}
    if version >= V10_TILDE:
        values = {k: ("" if v == "~" else v) for k, v in values.items()}
    for k, v in (p.fields or {}).items():
        values[k] = v
    lib_props = {str(n.items[1]): n for n in lib_node.children("property")}
    order = ["Reference", "Value", "Footprint", "Datasheet", "Description"] + [k for k in values if k not in
                                                                             ("Reference", "Value", "Footprint", "Datasheet", "Description")]
    for k in order:
        if k == "Description" and k not in lib_props and k not in values:
            continue
        v = values.get(k, str(lib_props[k].items[2]) if k in lib_props else "")
        lp = lib_props.get(k)
        if lp is not None:
            at = lp.xy() or [0, 0, 0]
            dx, dy = sym_transform(at[0], at[1], p.angle, p.mirror)
            tang = (at[2] if len(at) > 2 else 0)
            if int(p.angle) % 180 == 90 and k in ("Reference", "Value"):
                # Autoplace like KiCad: horizontal text above (ref) / below (value) the rotated body.
                x0, y0, x1, y1 = lib.bbox
                corners = [sym_transform(cx, cy, p.angle, p.mirror) for cx, cy in ((x0, y0), (x1, y1))]
                top = min(c[1] for c in corners)
                bot = max(c[1] for c in corners)
                # Field angles are stored in the symbol's frame; KiCad rotates them with the symbol.
                dx, dy, tang = 0.0, (top - 1.27) if k == "Reference" else (bot + 1.27), (0 - int(p.angle)) % 180
            eff = lp.child("effects")
            if int(p.angle) % 180 == 90 and k in ("Reference", "Value") and eff is not None:
                eff = _strip_justify(eff)
            hidden = (eff is not None and eff.has_flag("hide")) or lp.has_flag("hide")
        else:
            dx, dy, tang, eff, hidden = 0.0, 0.0, 0, None, True
        if k in ("Footprint", "Datasheet", "Description") or k not in ("Reference", "Value"):
            hidden = True if lp is None or hidden else hidden
        items.append(["property", QStr(k), QStr(v), ["at", round(p.x + dx, 4), round(p.y + dy, 4), int(tang)],
                      _effects_hidden(eff, hidden, version)])
    for pn in sorted({pin.number for pin in lib.pins_for_unit(p.unit)}, key=_nat):
        items.append(["pin", QStr(pn), ["uuid", _uuid_atom(new_uuid(), version)]])
    paths = []
    for ip in instance_paths:
        ip, ref = ip if isinstance(ip, tuple) else (ip, p.ref)
        paths.append(["path", QStr(ip), ["reference", QStr(ref)], ["unit", p.unit]])
    items.append(["instances", ["project", QStr(project), *paths]])
    return items


def label_nodes(lib: LibSymbol, p: Placement, pin_to_net: Dict[str, str], version: int,
                global_nets: Optional[set] = None) -> List[list]:
    """Labels anchored exactly at pin ends, text pointing away from the body. Nets in ``global_nets``
    (nets that leave this sheet) get global labels so they join across sheets; the rest get local labels."""
    out = []
    for pin in lib.pins_for_unit(p.unit):
        net = pin_to_net.get(pin.number)
        if not net:
            continue
        dx, dy = sym_transform(pin.x, pin.y, p.angle, p.mirror)
        x, y = round(p.x + dx, 4), round(p.y + dy, 4)
        # pin angle is the direction from connection point toward the body (library coords, CCW, Y up)
        ang = _pin_screen_angle(pin.angle, p.angle, p.mirror)
        label_ang = (ang + 180) % 360  # text reads away from the body
        just = "left" if label_ang in (0, 90) else "right"
        is_global = bool(global_nets) and net in global_nets
        head = ["global_label", QStr(net), ["shape", "bidirectional"]] if is_global else ["label", QStr(net)]
        out.append([*head, ["at", x, y, int(label_ang)],
                    ["fields_autoplaced", "yes"] if version >= V8 else ["fields_autoplaced"],
                    ["effects", ["font", ["size", 1.27, 1.27]], ["justify", just, "bottom"]],
                    ["uuid", _uuid_atom(new_uuid(), version)]])
    return out


def _pin_screen_angle(pin_angle, sym_angle, mirror):
    # vector pointing from pin end into body, in library coords
    import math
    r = math.radians(pin_angle)
    vx, vy = math.cos(r), math.sin(r)
    sx, sy = sym_transform(vx, vy, sym_angle, mirror)  # screen coords, Y down
    ang = math.degrees(math.atan2(-sy, sx)) % 360
    return int(round(ang / 90.0)) * 90 % 360


def _nat(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


# ---------------------------------------------------------------------------
class SchematicPlacer:
    def __init__(self, sch_path: str, source: SymbolSource, root_path: Optional[str] = None):
        self.sch_path = os.path.abspath(sch_path)
        self.source = source
        self.root_path = root_path or self._guess_root()
        self.hier = Hierarchy(self.root_path)
        self.sch = self.hier.load(self.sch_path)
        self.version = self.sch.version or 20231120
        self.project = self.hier.project_name
        self.occupied: List[Tuple[float, float, float, float]] = [self.sch.symbol_bbox(s) for s in self.sch.symbols]
        for sh in self.sch.sheets:
            self.occupied.append((sh.x, sh.y, sh.x + sh.w, sh.y + sh.h))
        paper = str(self.sch.root.value("paper", "A4") or "A4")
        self.page = PAPER.get(paper, (297, 210))
        self.existing_refs = {ref for _, _, ref, _ in self.hier.iter_symbols()}
        # pin positions of parts already on this sheet: "REF.PIN" -> (pin_x, pin_y, body_x, body_y)
        self.placed_pins: Dict[str, tuple] = {}
        for inst in self.hier.instances:
            if not _same(inst.sch.path, self.sch_path):
                continue
            for sym in inst.sch.symbols:
                ref, unit = sym.ref_for_path(inst.path)
                for pin, x, y in inst.sch.pin_positions(sym, unit):
                    self.placed_pins[f"{ref}.{pin.number}"] = (x, y, sym.x, sym.y)
            break

    def _guess_root(self):
        d = os.path.dirname(self.sch_path)
        pros = [f for f in os.listdir(d) if f.endswith(".kicad_pro")]
        if pros:
            return os.path.join(d, os.path.splitext(pros[0])[0] + ".kicad_sch")
        return self.sch_path

    def instance_paths(self) -> List[str]:
        root_uuid = self.hier.root.uuid
        paths = []
        for inst in self.hier.instances:
            if _same(inst.sch.path, self.sch_path):
                paths.append(f"/{root_uuid}{inst.path}" if inst.path else f"/{root_uuid}")
        return paths or [f"/{root_uuid}"]

    def _instance_refs(self, ref: str, unit: int):
        """Each copy of a repeated sheet needs its own reference: R5 on the first, next free R* on the others."""
        paths = self.instance_paths()
        if len(paths) == 1:
            return [(paths[0], ref)]
        if not hasattr(self, "_rep_refs"):
            self._rep_refs = {}
        if ref in self._rep_refs:  # further units of the same part reuse the same per-sheet references
            return list(zip(paths, self._rep_refs[ref]))
        m = re.match(r"^([A-Za-z#_]+)(\d+)$", ref)
        prefix, n = (m.group(1), int(m.group(2))) if m else (ref, 1)
        refs = [ref]
        taken = set(self.existing_refs) | {ref}
        while len(refs) < len(paths):
            n += 1
            if f"{prefix}{n}" not in taken:
                refs.append(f"{prefix}{n}")
                taken.add(f"{prefix}{n}")
        self.existing_refs |= set(refs)
        self._rep_refs[ref] = refs
        return list(zip(paths, refs))

    # -------------------------------------------------------------- layout
    def free_spot(self, w: float, h: float, near: Optional[Tuple[float, float]] = None, margin: float = 2.54):
        """Find a grid-aligned origin for a w x h box (centered at origin) that overlaps nothing."""
        pw, ph = self.page
        border = 12.7
        cands = []
        if near:
            cx, cy = near
            for r in range(0, 60):
                ring = []
                for dx in range(-r, r + 1):
                    for dy in (-r, r) if abs(dx) != r else range(-r, r + 1):
                        ring.append((cx + dx * 2.54, cy + dy * 2.54))
                ring.sort(key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2)  # closest first within the ring
                cands += ring
                if len(cands) > 9000:
                    break
        else:
            y = border + h / 2
            while y < ph * 3:
                x = border + w / 2
                while x < pw - border - w / 2:
                    cands.append((x, y))
                    x += 5.08
                y += 5.08
        for x, y in cands:
            x, y = snap(x, 2.54), snap(y, 2.54)
            box = (x - w / 2 - margin, y - h / 2 - margin, x + w / 2 + margin, y + h / 2 + margin)
            if box[0] < border or box[1] < border:
                continue
            if not any(_overlap(box, o) for o in self.occupied):
                return x, y
        return snap(pw + 25.4, 2.54), snap(border + len(self.occupied) * 12.7, 2.54)

    def reserve(self, lib: LibSymbol, x, y, angle=0, mirror=None):
        x0, y0, x1, y1 = lib.bbox
        pts = [sym_transform(px, py, angle, mirror) for px, py in ((x0, y0), (x1, y1), (x0, y1), (x1, y0))]
        xs = [x + p[0] for p in pts]
        ys = [y + p[1] for p in pts]
        box = (min(xs) - 2.54, min(ys) - 3.81, max(xs) + 2.54, max(ys) + 3.81)  # room for ref/value text
        self.occupied.append(box)
        return box

    @staticmethod
    def body_size(lib: LibSymbol, angle=0):
        x0, y0, x1, y1 = lib.bbox
        w, h = (x1 - x0) + 7.62, (y1 - y0) + 7.62
        return (h, w) if int(angle) % 180 == 90 else (w, h)

    # -------------------------------------------------------------- main API
    def place(self, items: List[Placement], mode: str = "file", labels: bool = False,
              pin_nets: Optional[Dict[str, Dict[str, str]]] = None, auto_position: bool = True,
              global_nets: Optional[set] = None) -> dict:
        """Place symbols. ``pin_nets``: {ref: {pin_number: net}} used for optional labels."""
        pin_nets = pin_nets or {}
        placed, skipped, missing = [], [], []
        new_nodes: List[list] = []
        lib_nodes: Dict[str, Node] = {}
        layout = {}
        if auto_position and pin_nets:
            try:
                layout = self._cluster_layout([p for p in items if not (p.ref in self.existing_refs and mode == "file")], pin_nets)
            except Exception:
                layout = {}
        for p in items:
            if p.ref in self.existing_refs and mode == "file":
                skipped.append(f"{p.ref} already exists in the schematic")
                continue
            lib, lnode = self._lib(p.lib_id)
            if lib is None:
                missing.append(f"{p.ref}: symbol {p.lib_id} not found in libraries")
                continue
            units = [p.unit] if p.unit else [1]
            if lib.unit_count > 1 and not p.unit:
                units = list(range(1, lib.unit_count + 1))
            for u in units:
                q = Placement(**{**p.__dict__, "unit": u})
                if (q.ref, u) in layout:
                    q.x, q.y, q.angle = layout[(q.ref, u)]
                elif auto_position or q.x == 0 and q.y == 0:
                    near = (q.x, q.y) if (q.x or q.y) else self._affinity_point(lib, q, pin_nets)
                    if near and _is_two_pin(lib):
                        # orient two-pin parts so their pins run along the line toward the partner pin
                        q.angle = near[2] if len(near) > 2 else q.angle
                    w, h = self.body_size(lib, q.angle)
                    q.x, q.y = self.free_spot(w, h, near[:2] if near else None)
                else:
                    q.x, q.y = snap(q.x, SCH_GRID), snap(q.y, SCH_GRID)
                self.reserve(lib, q.x, q.y, q.angle, q.mirror)
                node = build_symbol_node(q, lib, lnode, self.project, self._instance_refs(q.ref, u), self.version)
                new_nodes.append(node)
                if labels and p.ref in pin_nets:
                    new_nodes += label_nodes(lib, q, pin_nets[p.ref], self.version, global_nets)
                table = self._pin_table(lib, q)
                for row in table:
                    self.placed_pins[f"{q.ref}.{row['pin']}"] = (row["at_mm"][0], row["at_mm"][1], q.x, q.y)
                placed.append({"ref": q.ref, "unit": u, "lib_id": q.lib_id, "at_mm": [q.x, q.y], "angle": q.angle,
                               "pins": table})
            if p.lib_id not in self.sch.lib_symbols:
                lib_nodes[p.lib_id] = _modernize_tilde(lnode) if self.version >= V10_TILDE else lnode
            self.existing_refs.add(p.ref)
        result = {"placed": placed, "skipped": skipped, "missing": missing}
        if not new_nodes:
            return result
        if mode == "clipboard":
            text = ""
            cache = list(lib_nodes.values()) + [self.sch.lib_symbols[i].node for i in {p.lib_id for p in items}
                                                  if i in self.sch.lib_symbols]
            if cache:
                text += dump(["lib_symbols", *cache]) + "\n"
            text += "\n".join(dump(n) for n in new_nodes) + "\n"
            result["clipboard_text"] = text
            result["how_to_paste"] = ("Click in the KiCad schematic editor, press Ctrl+V, move the mouse to where you want the "
                                      "group and left-click to drop it. Then press Escape.")
            return result
        lock = lock_file_for(self.sch_path)
        result["backup"] = backup(self.sch_path)
        text = self.sch.text
        # 1) lib_symbols cache entries
        if lib_nodes:
            ls = self.sch.root.child("lib_symbols")
            add = "".join("\n\t\t" + dump(n, 2) for n in lib_nodes.values())
            if ls is not None:
                pos = ls.end - 1
                text = text[:pos] + add + "\n\t" + text[pos:]
                shift = len(add) + 2
            else:
                pos = self._after_header()
                ins = f"\n\t(lib_symbols{add}\n\t)"
                text = text[:pos] + ins + text[pos:]
                shift = len(ins)
        else:
            shift = 0
            pos = -1
        # 2) symbol instances before (sheet_instances ...) or before the final ')'
        si = self.sch.root.child("sheet_instances")
        anchor = si.start if si is not None else self.sch.root.end - 1
        for other in ("embedded_fonts",):
            n = self.sch.root.child(other)
            if n is not None and si is None:
                anchor = min(anchor, n.start)
        if pos != -1 and pos <= anchor:
            anchor += shift
        block = "".join(dump(n, 1) + "\n\t" for n in new_nodes)
        text = text[:anchor] + block + text[anchor:]
        parse(text)  # sanity check: the result must be a valid s-expression
        with open(self.sch_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        result["written"] = self.sch_path
        if lock:
            result["warning"] = ("The schematic is open in KiCad (lock file present). KiCad will NOT show these parts until "
                                 "you reload, and saving from KiCad now would erase them. In KiCad: close the schematic "
                                 "without saving and reopen it — or next time use clipboard mode.")
        else:
            result["next_step"] = "Open the schematic in KiCad; the parts are placed with footprints assigned and no wires."
        return result

    # ------------------------------------------------------------------ clustered layout
    def _cluster_layout(self, items: List["Placement"], pin_nets) -> Dict[tuple, tuple]:
        """Group each IC with the passives that serve it, lay the group out around the IC's pins, then pack groups.

        Returns {(ref, unit): (x, y, angle)} in sheet coordinates.
        """
        libs = {}
        for p in items:
            lib, _ = self._lib(p.lib_id)
            if lib is not None:
                libs[p.ref] = (p, lib)
        is_anchor = lambda ref: bool(re.match(r"^(U|IC|Q|VR|PS|K|J|P|CN|X|SW|T)\d", ref))  # noqa: E731
        ic_like = lambda ref: bool(re.match(r"^(U|IC|Q|VR|PS|K)\d", ref))  # noqa: E731
        net_members: Dict[str, List[str]] = {}
        for ref, pins in pin_nets.items():
            for pn, net in pins.items():
                net_members.setdefault(net, []).append(f"{ref}.{pn}")
        # anchor units
        anchors = []
        for ref, (p, lib) in libs.items():
            npins = len({pp.number for pp in lib.pins})
            small_conn = bool(re.match(r"^(J|P|CN|X)\d", ref)) and npins <= 6
            if (is_anchor(ref) and not small_conn) or npins > 6:
                units = [p.unit] if p.unit else list(range(1, lib.unit_count + 1))
                for u in units:
                    anchors.append((ref, u))
        anchor_refs = {a[0] for a in anchors}
        unit_of_pin = {}
        for ref, u in anchors:
            for pp in libs[ref][1].pins_for_unit(u):
                unit_of_pin[(ref, pp.number)] = u
        members: Dict[tuple, List[tuple]] = {a: [] for a in anchors}
        for ref, (p, lib) in libs.items():
            if ref in anchor_refs:
                continue
            best = None
            for pn, net in (pin_nets.get(ref) or {}).items():
                if re.match(r"^(GND|VSS|0V|AGND|DGND|PGND)", net, re.I):
                    continue
                size = len(net_members.get(net, []))
                for other in net_members.get(net, []):
                    oref, opn = other.split(".", 1)
                    if oref == ref or oref not in anchor_refs:
                        continue
                    score = (0 if ic_like(oref) else 1, size)
                    if best is None or score < best[0]:
                        best = (score, (oref, unit_of_pin.get((oref, opn), 1)), opn, pn)
            if best:
                members[best[1]].append((ref, best[2], best[3]))
        # passives with no IC on this sheet: chain them to a partner passive (dividers, RC filters, LED+R ...)
        owner = {}
        for a, ms in members.items():
            owner[a[0]] = a
            for m in ms:
                owner[m[0]] = a
        pending = [ref for ref in libs if ref not in owner]
        while pending:
            progress = False
            for ref in list(pending):
                partner = None
                for pn, net in (pin_nets.get(ref) or {}).items():
                    if re.match(r"^(GND|VSS|0V|AGND|DGND|PGND)", net, re.I) or len(net_members.get(net, [])) > 8:
                        continue
                    for other in net_members.get(net, []):
                        oref = other.split(".", 1)[0]
                        if oref != ref and oref in owner:
                            partner = oref
                            break
                    if partner:
                        break
                if partner:
                    a = owner[partner]
                    members[a].append((ref, None, None, partner))
                    owner[ref] = a
                    pending.remove(ref)
                    progress = True
            if not progress and pending:
                seed = pending.pop(0)  # start a new mini-cluster
                p0, l0 = libs[seed]
                a = (seed, p0.unit or 1)
                anchors.append(a)
                members[a] = []
                owner[seed] = a
        out: Dict[tuple, tuple] = {}
        for anchor in anchors:
            aref, au = anchor
            ap, alib = libs[aref]
            local_occ = []
            x0, y0, x1, y1 = alib.bbox
            corners = [sym_transform(cx, cy, 0, None) for cx, cy in ((x0, y0), (x1, y1))]
            abox = (min(c[0] for c in corners) - 2.54, min(c[1] for c in corners) - 3.81,
                    max(c[0] for c in corners) + 2.54, max(c[1] for c in corners) + 3.81)
            local_occ.append(abox)
            local = {(aref, au): (0.0, 0.0, 0)}
            apins = {pp.number: pp for pp in alib.pins_for_unit(au)}
            for entry in members.get(anchor, []):
                mref, apin, mpin = entry[:3]
                mp, mlib = libs[mref]
                if len(entry) > 3:  # chained to a partner passive
                    partner = entry[3]
                    pk = next((k for k in local if k[0] == partner), None)
                    if pk is None:
                        continue
                    ppx, ppy, pang = local[pk]
                    angle = pang if _is_two_pin(mlib) else 0
                    w, h = self.body_size(mlib, angle)
                    pos = _spiral_fit(ppx, ppy + 7.62, w, h, local_occ, (0, 1))
                    local_occ.append((pos[0] - w / 2, pos[1] - h / 2, pos[0] + w / 2, pos[1] + h / 2))
                    units = [mp.unit] if mp.unit else list(range(1, mlib.unit_count + 1))
                    local[(mref, units[0])] = (pos[0], pos[1], angle)
                    continue
                pp = apins.get(apin)
                if pp is None:
                    continue
                px, py = sym_transform(pp.x, pp.y, 0, None)
                inward = _pin_screen_angle(pp.angle, 0, None)
                ox, oy = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}.get(inward, (1, 0))
                angle = (90 if ox else 0) if _is_two_pin(mlib) else 0  # 2-pin passives lie along the pin direction
                w, h = self.body_size(mlib, angle)
                reach = (w if ox else h) / 2 + 3.81
                tx, ty = px + ox * reach, py + oy * reach
                pos = _spiral_fit(tx, ty, w, h, local_occ, (ox, oy))
                local_occ.append((pos[0] - w / 2, pos[1] - h / 2, pos[0] + w / 2, pos[1] + h / 2))
                units = [mp.unit] if mp.unit else list(range(1, mlib.unit_count + 1))
                local[(mref, units[0])] = (pos[0], pos[1], angle)
            bx0 = min(b[0] for b in local_occ)
            by0 = min(b[1] for b in local_occ)
            bx1 = max(b[2] for b in local_occ)
            by1 = max(b[3] for b in local_occ)
            gx, gy = self.free_spot(bx1 - bx0 + 2.54, by1 - by0 + 2.54, None, margin=2.54)
            offx = snap(gx - (bx0 + bx1) / 2, 2.54)
            offy = snap(gy - (by0 + by1) / 2, 2.54)
            self.occupied.append((bx0 + offx - 1.27, by0 + offy - 1.27, bx1 + offx + 1.27, by1 + offy + 1.27))
            for key_, (lx, ly, ang) in local.items():
                out[key_] = (snap(lx + offx, SCH_GRID), snap(ly + offy, SCH_GRID), ang)
        return out

    def _affinity_point(self, lib: LibSymbol, q: "Placement", pin_nets):
        """A point next to an already-placed pin that shares a net with this part (outward from that part's body)."""
        mine = (pin_nets or {}).get(q.ref) or {}
        if not mine:
            return None
        net_to_pins: Dict[str, list] = {}
        for ref, pins in (pin_nets or {}).items():
            if ref == q.ref:
                continue
            for pn, net in pins.items():
                net_to_pins.setdefault(net, []).append(f"{ref}.{pn}")
        best = None
        for pn, net in mine.items():
            if re.match(r"^(GND|VSS|0V)", net, re.I):
                continue  # ground is everywhere: don't anchor on it
            for other in net_to_pins.get(net, []):
                if other in self.placed_pins:
                    px, py, bx, by = self.placed_pins[other]
                    # prefer the IC pin a passive serves, then the most specific (smallest) net
                    is_ic = 0 if re.match(r"^(U|IC|Q|VR|PS)\d", other.split(".")[0]) else 1
                    score = (is_ic, len(net_to_pins.get(net, [])))
                    if best is None or score < best[0]:
                        best = (score, px, py, bx, by)
        if not best:
            return None
        _, px, py, bx, by = best
        dx, dy = px - bx, py - by
        horizontal = abs(dx) >= abs(dy)
        step = 10.16
        if horizontal:
            return (px + (step if dx >= 0 else -step), py, 90)  # pin sticks out left/right: lay the part horizontally
        return (px, py + (step if dy >= 0 else -step), 0)

    def _after_header(self):
        for h in ("paper", "uuid", "generator_version", "generator", "version"):
            n = self.sch.root.child(h)
            if n is not None:
                tb = self.sch.root.child("title_block")
                return max(n.end, tb.end if tb is not None else 0)
        return len("(kicad_sch")

    def _lib(self, lib_id):
        if lib_id in self.sch.lib_symbols:
            lib = self.sch.lib_symbols[lib_id]
            return lib, lib.node
        return self.source.get(lib_id)

    def _pin_table(self, lib: LibSymbol, p: Placement):
        rows = []
        for pin in lib.pins_for_unit(p.unit):
            dx, dy = sym_transform(pin.x, pin.y, p.angle, p.mirror)
            rows.append({"pin": pin.number, "name": pin.name, "at_mm": [round(p.x + dx, 3), round(p.y + dy, 3)]})
        return sorted(rows, key=lambda r: _nat(r["pin"]))


def _modernize_tilde(node: Node) -> Node:
    """Older libraries use "~" for empty pin names / fields; KiCad 10 files treat "~" literally."""
    from copy import deepcopy
    n = deepcopy(node)
    for sub in n.find_all("name"):
        if len(sub.items) > 1 and sub.items[1] == "~":
            sub.items[1] = QStr("")
    for prop in n.find_all("property"):
        if len(prop.items) > 2 and prop.items[2] == "~":
            prop.items[2] = QStr("")
    return n


def _spiral_fit(tx, ty, w, h, occupied, direction, step=2.54, max_r=40):
    """Closest free spot to (tx, ty) for a w x h box, preferring positions further along ``direction``."""
    ox, oy = direction
    best = None
    for r in range(0, max_r):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                x, y = tx + dx * step, ty + dy * step
                # never step back toward/inside the anchor along the pin direction
                if (ox and (x - tx) * ox < 0) or (oy and (y - ty) * oy < 0):
                    continue
                box = (x - w / 2 - 1.27, y - h / 2 - 1.27, x + w / 2 + 1.27, y + h / 2 + 1.27)
                if not any(_overlap(box, o) for o in occupied):
                    d = (x - tx) ** 2 + (y - ty) ** 2
                    if best is None or d < best[0]:
                        best = (d, x, y)
        if best:
            return best[1], best[2]
    return tx, ty


def _is_two_pin(lib: LibSymbol) -> bool:
    return len({p.number for p in lib.pins}) == 2


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


# ---------------------------------------------------------------------------
def sync_fields(hier: Hierarchy, plan, fields=("Value", "Footprint"), extra_fields: bool = True) -> dict:
    """Write plan values/footprints/extra fields (MPN, LCSC...) into already-placed symbols (all sheets).

    Only the affected (property ...) nodes are rewritten; everything else in each file is left untouched.
    """
    changes, files = [], {}
    by_ref = {c.ref: c for c in plan.components}
    for inst, sym, ref, unit in hier.iter_symbols():
        c = by_ref.get(ref)
        if c is None or sym.node is None:
            continue
        want = {}
        if "Value" in fields and c.value:
            want["Value"] = c.value
        if "Footprint" in fields and c.footprint:
            want["Footprint"] = c.footprint
        if extra_fields:
            want.update({k: v for k, v in (c.fields or {}).items() if v})
        sch = inst.sch
        edits = files.setdefault(sch.path, (sch, []))[1]
        existing = {str(pn.items[1]): pn for pn in sym.node.children("property")}
        last_prop = None
        for pn in sym.node.children("property"):
            last_prop = pn
        for k, v in want.items():
            pn = existing.get(k)
            if pn is not None:
                if str(pn.items[2]) == v:
                    continue
                new = Node(list(pn.items))
                new.items[2] = QStr(v)
                edits.append((pn.start, pn.end, dump(new, 2)))
                changes.append(f"{ref}: {k} '{pn.items[2]}' → '{v}'")
            elif last_prop is not None:
                eff = ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"] if sch.version >= V8 else "hide"]
                txt = dump(["property", QStr(k), QStr(v), ["at", sym.x, sym.y, 0], eff], 2)
                edits.append((last_prop.end, last_prop.end, "\n\t\t" + txt))
                changes.append(f"{ref}: added {k} = '{v}'")
    written = []
    for path, (sch, edits) in files.items():
        if not edits:
            continue
        # a symbol shared by repeated sheets is visited once per instance: de-duplicate identical edits
        uniq = sorted(set(edits), key=lambda e: -e[0])
        text = sch.text
        backup(path)
        for s0, e0, rep in uniq:
            text = text[:s0] + rep + text[e0:]
        parse(text)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        written.append(path)
    return {"changes": sorted(set(changes)), "files_written": written,
            "warning": "Reload the schematic in KiCad (close without saving, reopen) to see the changes." if written else None}
