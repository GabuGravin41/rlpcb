"""Geometric connectivity for KiCad schematics.

Computes nets from the drawing itself (pins, wires, junctions, labels, power
symbols, hierarchical sheets) so the copilot can:
  * tell the user exactly what is connected to what,
  * detect "ghost" wires (floating, dangling, near-miss endpoints),
  * verify a hand-drawn schematic against an intended design plan.

Rules follow KiCad's connectivity model:
  * any point item (pin end, label anchor, wire end, junction, sheet pin)
    connects to every wire segment it lies on (end or interior);
  * two wire segments whose interiors merely cross are NOT connected;
  * local labels join within one sheet instance; global labels and power
    symbols join design-wide; hierarchical labels join the matching sheet pin
    in the parent sheet instance;
  * hidden power_in pins on ordinary symbols join the global net named after the pin.
Bus unfolding is not modelled (bus wires are ignored and reported).
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .geometry import IU, key, point_on_segment
from .schematic import Hierarchy, SheetInstance


class DSU:
    def __init__(self):
        self.p = {}

    def find(self, a):
        p = self.p
        p.setdefault(a, a)
        root = a
        while p[root] != root:
            root = p[root]
        while p[a] != root:
            p[a], a = root, p[a]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


@dataclass
class PinRef:
    ref: str
    pin: str
    name: str
    etype: str
    sheet: str
    x: float
    y: float
    hidden: bool = False

    def label(self):
        nm = f" ({self.name})" if self.name and self.name != "~" and self.name != self.pin else ""
        return f"{self.ref}.{self.pin}{nm}"


@dataclass
class Net:
    name: str
    pins: List[PinRef] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    sheets: set = field(default_factory=set)
    auto_named: bool = False

    def to_dict(self, max_pins=500):
        return {
            "name": self.name,
            "pins": [p.label() for p in sorted(self.pins, key=lambda p: (p.ref, p.pin))][:max_pins],
            "pin_count": len(self.pins),
            "labels": sorted(set(self.labels)),
        }


@dataclass
class Issue:
    severity: str  # error | warning | info
    kind: str
    message: str
    sheet: str = ""
    x: Optional[float] = None
    y: Optional[float] = None

    def to_dict(self):
        d = {"severity": self.severity, "kind": self.kind, "message": self.message, "sheet": self.sheet}
        if self.x is not None:
            d["at_mm"] = [round(self.x, 3), round(self.y, 3)]
        return d


class Connectivity:
    def __init__(self, hier: Hierarchy, near_miss_mm: float = 1.3):
        self.h = hier
        self.near_miss = near_miss_mm
        self.dsu = DSU()
        self.nets: Dict[str, Net] = {}
        self.issues: List[Issue] = []
        self.pin_net: Dict[Tuple[str, str], str] = {}
        self._pins: Dict[tuple, PinRef] = {}
        self._names: Dict[str, List[Tuple[int, str]]] = defaultdict(list)  # root -> [(priority, name)]
        self._local_rep: Dict[Tuple[str, str], str] = {}
        self._nc_items: List[tuple] = []
        self._nc_pins = set()
        self._bus_points: Dict[str, tuple] = {}
        self.aliases: Dict[str, List[str]] = hier.bus_aliases() if hasattr(hier, "bus_aliases") else {}
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        global_names: Dict[str, str] = {}  # name -> item id
        sheet_pin_items: Dict[Tuple[str, str], str] = {}  # (child_path, pin name) -> item id in parent
        hier_label_items: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        for inst in self.h.instances:
            self._build_sheet(inst, global_names, sheet_pin_items, hier_label_items)
        # hierarchical label <-> sheet pin
        for (path, name), items in hier_label_items.items():
            sp = sheet_pin_items.get((path, name))
            for it in items:
                if sp:
                    self.dsu.union(it, sp)
                else:
                    self.issues.append(Issue("warning", "hier_label_without_sheet_pin",
                                             f"Hierarchical label '{name}' has no matching sheet pin in the parent sheet", path))
        for (path, name), it in sheet_pin_items.items():
            members = expand_bus(name, self.aliases)
            if members:
                parent, sheet_uuid = path.rsplit("/", 1)
                for m in members:
                    a = self._member_node(path, m)
                    b = self._sheetpin_member(parent, sheet_uuid, m)
                    self.dsu.union(a, b)
            if (path, name) not in hier_label_items:
                self.issues.append(Issue("warning", "sheet_pin_without_hier_label",
                                         f"Sheet pin '{name}' has no matching hierarchical label inside the sheet", path))
        self._collect_nets()

    def _build_sheet(self, inst: SheetInstance, global_names, sheet_pin_items, hier_label_items):
        sch = inst.sch
        sp = inst.path
        dsu = self.dsu
        at_point: Dict[tuple, List[str]] = defaultdict(list)
        point_kind: Dict[str, str] = {}
        wires = [w for w in sch.wires if not w.bus]
        if any(w.bus for w in sch.wires):
            self.issues.append(Issue("info", "bus_not_modelled",
                                     "Sheet contains buses; bus members are only connected through labels in this analysis", inst.name_path))
        wid = [f"{sp}|w{i}" for i in range(len(wires))]
        wkeys = [(key(w.x1, w.y1), key(w.x2, w.y2)) for w in wires]

        def add_point(item_id, x, y, kind):
            k = key(x, y)
            at_point[k].append(item_id)
            point_kind[item_id] = kind
            dsu.find(item_id)
            return k

        # wire endpoints
        for i, (a, b) in enumerate(wkeys):
            at_point[a].append(f"{wid[i]}|a")
            at_point[b].append(f"{wid[i]}|b")
            point_kind[f"{wid[i]}|a"] = point_kind[f"{wid[i]}|b"] = "wire_end"
            dsu.union(f"{wid[i]}|a", wid[i])
            dsu.union(f"{wid[i]}|b", wid[i])
        # pins
        local_power: Dict[str, List[str]] = defaultdict(list)
        for s in sch.symbols:
            ref, unit = s.ref_for_path(sp)
            lib = sch.lib_for(s)
            if lib is None:
                self.issues.append(Issue("error", "missing_lib_symbol", f"{ref}: symbol '{s.lib_id}' not found in lib_symbols cache", inst.name_path, s.x, s.y))
                continue
            for p, x, y in sch.pin_positions(s, unit):
                iid = f"{sp}|pin|{ref}|{p.number}|{unit}|{x}|{y}"
                if p.etype == "no_connect":
                    dsu.find(iid)  # KiCad never connects pins of type no_connect
                else:
                    add_point(iid, x, y, "pin")
                pr = PinRef(ref, p.number, p.name, p.etype, inst.name_path, x, y, p.hidden)
                self._pins[iid] = pr
                if lib.power and p.etype == "power_in":
                    # KiCad >= 8 names power nets after the Value field; KiCad 6/7 used the pin name.
                    netname = (s.value or p.name) if sch.version >= 20231120 else (p.name or s.value)
                    netname = _unesc_name(netname)
                    if getattr(lib, "power_scope", "global") == "local":
                        local_power[netname].append(iid)  # KiCad 10 local power: joins only on this sheet
                        self._names[iid].append((1, inst.name_path + netname))
                    else:
                        self._global(global_names, netname, iid, 0)
                elif p.hidden and p.etype == "power_in":
                    self._global(global_names, p.name, iid, 1)
        for items in local_power.values():
            for it in items[1:]:
                dsu.union(items[0], it)
        # labels
        local_labels: Dict[str, List[str]] = defaultdict(list)
        for i, lb in enumerate(sch.labels):
            iid = f"{sp}|lbl{i}|{lb.kind}|{lb.text}"
            add_point(iid, lb.x, lb.y, lb.kind)
            if lb.kind == "global_label":
                self._global(global_names, lb.text, iid, 2)
            elif lb.kind == "label":
                local_labels[lb.text].append(iid)
                self._names[iid].append((3, (inst.name_path if inst.name_path != "/" else "/") + lb.text))
            elif lb.kind == "hierarchical_label":
                hier_label_items[(sp, lb.text)].append(iid)
                self._names[iid].append((4, inst.name_path + lb.text))
        for name, items in local_labels.items():
            for it in items[1:]:
                dsu.union(items[0], it)
            self._local_rep[(sp, name)] = items[0]
        # local and hierarchical labels with the same text join within a sheet
        for i, lb in enumerate(sch.labels):
            if lb.kind == "hierarchical_label":
                iid = f"{sp}|lbl{i}|{lb.kind}|{lb.text}"
                rep = self._local_rep.get((sp, lb.text))
                if rep:
                    dsu.union(rep, iid)
                else:
                    self._local_rep[(sp, lb.text)] = iid
        self._build_buses(inst)
        # bus entries: both ends are connection points for wires
        for i, (x1, y1, x2, y2) in enumerate(sch.bus_entries):
            add_point(f"{sp}|be{i}a", x1, y1, "bus_entry")
            add_point(f"{sp}|be{i}b", x2, y2, "bus_entry")
        # junctions & no-connects
        nc_keys = set()
        for i, (x, y) in enumerate(sch.junctions):
            add_point(f"{sp}|j{i}", x, y, "junction")
        for i, (x, y) in enumerate(sch.no_connects):
            nc_keys.add(key(x, y))
            nid = f"{sp}|nc{i}"
            add_point(nid, x, y, "no_connect")
            self._nc_items.append((nid, inst.name_path, x, y))
        # sheet pins
        for sh in sch.sheets:
            child_path = f"{sp}/{sh.uuid}"
            for p in sh.pins:
                iid = f"{sp}|sheetpin|{sh.uuid}|{p.name}"
                add_point(iid, p.x, p.y, "sheet_pin")
                sheet_pin_items[(child_path, p.name)] = iid
                self._names[iid].append((5, f"{inst.name_path}{sh.name}/{p.name}"))
        # union all items at same point
        for k, items in at_point.items():
            for it in items[1:]:
                dsu.union(items[0], it)
        # items lying on wire segments (interior or endpoint)
        horiz = defaultdict(list)
        vert = defaultdict(list)
        diag = []
        for i, (a, b) in enumerate(wkeys):
            if a[1] == b[1]:
                horiz[a[1]].append(i)
            elif a[0] == b[0]:
                vert[a[0]].append(i)
            else:
                diag.append(i)
        on_wire: Dict[tuple, List[int]] = defaultdict(list)
        for k in at_point:
            cands = []
            for i in horiz.get(k[1], ()):
                a, b = wkeys[i]
                if min(a[0], b[0]) <= k[0] <= max(a[0], b[0]):
                    cands.append(i)
            for i in vert.get(k[0], ()):
                a, b = wkeys[i]
                if min(a[1], b[1]) <= k[1] <= max(a[1], b[1]):
                    cands.append(i)
            for i in diag:
                if point_on_segment(k, *wkeys[i]):
                    cands.append(i)
            kinds = {point_kind.get(it) for it in at_point[k]}
            only_wire_ends = kinds <= {"wire_end"}
            for i in cands:
                a, b = wkeys[i]
                interior = k != a and k != b
                if interior and only_wire_ends:
                    # KiCad does not connect a wire end to the middle of another wire
                    # unless a junction sits there. Report it: it looks connected but is not.
                    x, y = k[0] / IU, k[1] / IU
                    self.issues.append(Issue("error", "t_without_junction",
                                             f"Wire ends on the middle of another wire at ({x:.2f}, {y:.2f}) mm without a junction dot — "
                                             "KiCad treats these as NOT connected. Add a junction (or re-draw the wire) if they should connect.",
                                             inst.name_path, x, y))
                    continue
                on_wire[k].append(i)
                dsu.union(at_point[k][0], wid[i])
        # ---------------- geometry issues on this sheet
        pin_points = {}
        for iid, pr in self._pins.items():
            if iid.startswith(sp + "|pin|"):
                pin_points[key(pr.x, pr.y)] = pr
        for i, (a, b) in enumerate(wkeys):
            w = wires[i]
            for end, k in (("a", a), ("b", b)):
                others = [it for it in at_point[k] if not it.startswith(wid[i] + "|")]
                touching = [j for j in on_wire.get(k, []) if j != i]
                if not others and not touching:
                    x, y = k[0] / IU, k[1] / IU
                    near = self._nearest_pin(pin_points, k)
                    msg = f"Dangling wire end at ({x:.2f}, {y:.2f}) mm — connects to nothing"
                    if near is not None:
                        pr, d = near
                        msg += f"; nearest pin is {pr.label()} {d:.2f} mm away (near-miss: wire probably meant to end on that pin)"
                    self.issues.append(Issue("error", "dangling_wire_end", msg, inst.name_path, x, y))
        # completely floating wires (neither end connects to a pin/label/sheet pin through the wire network)
        self._floating_wire_check(inst, wires, wid)
        # off-grid pins (cause invisible misses)
        for k, pr in pin_points.items():
            if (k[0] % 127 != 0) or (k[1] % 127 != 0):  # 0.0127 mm quantum of the 1.27 grid in IU
                if (round(pr.x / 1.27, 3) % 1) != 0 or (round(pr.y / 1.27, 3) % 1) != 0:
                    self.issues.append(Issue("warning", "off_grid_pin",
                                             f"Pin {pr.label()} is off the 1.27 mm grid at ({pr.x}, {pr.y}); wires drawn on-grid will miss it",
                                             inst.name_path, pr.x, pr.y))
        # labels not touching anything
        for i, lb in enumerate(sch.labels):
            if lb.kind in ("netclass_flag", "directive_label"):
                continue
            k = key(lb.x, lb.y)
            bus_segs = self._bus_points.get(sp, ([],))[0]
            if len(at_point[k]) == 1 and not on_wire.get(k) and not any(point_on_segment(k, a, b) for a, b in bus_segs):
                msg = f"{lb.kind.replace('_', ' ')} '{lb.text}' is not attached to a wire or pin"
                near = self._nearest_pin(pin_points, k)
                if near is not None:
                    pr, d = near
                    msg += f"; nearest pin is {pr.label()} {d:.2f} mm away (near-miss: move the label onto that pin end)"
                self.issues.append(Issue("warning", "dangling_label", msg, inst.name_path, lb.x, lb.y))

    def _member_node(self, sp: str, member: str) -> str:
        """Virtual node representing bus member ``member`` inside sheet instance ``sp``."""
        nid = f"{sp}|bm|{member}"
        if nid not in self.dsu.p:
            self.dsu.find(nid)
            rep = self._local_rep.get((sp, member))
            if rep:
                self.dsu.union(nid, rep)
            else:
                self._local_rep[(sp, member)] = nid
        return nid

    def _sheetpin_member(self, parent_sp: str, sheet_uuid: str, member: str) -> str:
        """Node for bus member ``member`` of one sheet pin (distinct per sheet instance)."""
        nid = f"{parent_sp}|sp|{sheet_uuid}|{member}"
        self.dsu.find(nid)
        return nid

    def _build_buses(self, inst: SheetInstance):
        """Group bus segments with the bus labels / sheet pins on them and connect members.

        KiCad semantics: labels name the bus ("drivers"); a sheet pin on a bus that also carries a
        vector label maps its members by index onto the label's members; a sheet pin whose bus has
        no label contributes its own member names to the sheet. Group buses match by member name.
        """
        sch, sp = inst.sch, inst.path
        buses = [w for w in sch.wires if w.bus]
        seg_keys = [(key(w.x1, w.y1), key(w.x2, w.y2)) for w in buses]
        bd = DSU()
        pts = defaultdict(list)
        for i, (a, b) in enumerate(seg_keys):
            pts[a].append(i)
            pts[b].append(i)
            bd.find(i)
        for k, segs in pts.items():
            for j in segs[1:]:
                bd.union(segs[0], j)
        for k in pts:
            for i, (a, b) in enumerate(seg_keys):
                if k != a and k != b and point_on_segment(k, a, b):
                    bd.union(pts[k][0], i)

        def group_of(x, y):
            k = key(x, y)
            for i, (a, b) in enumerate(seg_keys):
                if point_on_segment(k, a, b):
                    return bd.find(i)
            return None
        labels = defaultdict(list)   # group -> [label text]
        pins = defaultdict(list)     # group -> [(sheet uuid, pin name)]
        for lb in sch.labels:
            if lb.kind in ("label", "hierarchical_label", "global_label") and expand_bus(lb.text, self.aliases):
                g = group_of(lb.x, lb.y)
                if g is not None:
                    labels[g].append(lb.text)
        handled = set()
        for sh in sch.sheets:
            for pn in sh.pins:
                if not expand_bus(pn.name, self.aliases):
                    continue
                g = group_of(pn.x, pn.y)
                if g is not None:
                    pins[g].append((sh.uuid, pn.name))
                    handled.add((sh.uuid, pn.name))
        for grp in set(labels) | set(pins):
            uniq = list(dict.fromkeys(labels.get(grp, [])))
            vec_labels = [expand_bus(n, self.aliases) for n in uniq if _split_group(n) is None and n not in self.aliases]
            grp_labels = [expand_bus(n, self.aliases) for n in uniq if _split_group(n) is not None or n in self.aliases]
            for n in uniq:
                for m in expand_bus(n, self.aliases):
                    self._member_node(sp, m)
            for other in vec_labels[1:]:
                for ma, mb in zip(vec_labels[0], other):
                    self.dsu.union(self._member_node(sp, ma), self._member_node(sp, mb))
            by_suffix = defaultdict(list)
            for g in grp_labels:
                for m in g:
                    by_suffix[_member_suffix(m)].append(m)
            for ms in by_suffix.values():
                for m in ms[1:]:
                    self.dsu.union(self._member_node(sp, ms[0]), self._member_node(sp, m))
            # sheet pins on this bus
            for uuid, pname in pins.get(grp, []):
                members = expand_bus(pname, self.aliases)
                is_group = _split_group(pname) is not None or pname in self.aliases
                if is_group and not grp_labels:
                    first_members = expand_bus(pins[grp][0][1], self.aliases)
                    targets = {_member_suffix(m): m for m in first_members}
                    for m in members:
                        t = targets.get(_member_suffix(m), m)
                        self.dsu.union(self._sheetpin_member(sp, uuid, m), self._member_node(sp, t))
                elif is_group:
                    targets = {_member_suffix(m): m for g in grp_labels for m in g}
                    for m in members:
                        t = targets.get(_member_suffix(m), m)
                        self.dsu.union(self._sheetpin_member(sp, uuid, m), self._member_node(sp, t))
                elif vec_labels:
                    for i, m in enumerate(members):
                        t = vec_labels[0][i] if i < len(vec_labels[0]) else m
                        self.dsu.union(self._sheetpin_member(sp, uuid, m), self._member_node(sp, t))
                else:
                    # no label on the bus: sheet pins share member names (and connect to each other by index)
                    first = pins[grp][0]
                    first_members = expand_bus(first[1], self.aliases)
                    for i, m in enumerate(members):
                        t = first_members[i] if i < len(first_members) else m
                        self.dsu.union(self._sheetpin_member(sp, uuid, m), self._member_node(sp, t))
        # bus sheet pins not on any bus: members behave like local labels of the parent sheet
        for sh in sch.sheets:
            for pn in sh.pins:
                if (sh.uuid, pn.name) in handled:
                    continue
                for m in expand_bus(pn.name, self.aliases):
                    self.dsu.union(self._sheetpin_member(sp, sh.uuid, m), self._member_node(sp, m))
        if seg_keys:
            self._bus_points.setdefault(sp, (seg_keys,))

    def _floating_wire_check(self, inst, wires, wid):
        # computed after all unions of this sheet; a wire group with no pins/labels/sheet pins is floating
        groups = defaultdict(list)
        for i in range(len(wires)):
            groups[self.dsu.find(wid[i])].append(i)
        self._pending_floating = getattr(self, "_pending_floating", [])
        self._pending_floating.append((inst, wires, wid, groups))

    def _global(self, global_names, name, iid, prio):
        if name in global_names:
            self.dsu.union(global_names[name], iid)
        else:
            global_names[name] = iid
        self._names[iid].append((prio, name))

    @staticmethod
    def _nearest_pin(pin_points, k, max_iu=None):
        best = None
        for pk, pr in pin_points.items():
            d = math.hypot(pk[0] - k[0], pk[1] - k[1]) / IU
            if d > 0 and (best is None or d < best[1]):
                best = (pr, d)
        if best and best[1] <= 2.6:
            return best
        return None

    # ------------------------------------------------------------------
    def _collect_nets(self):
        nc_ids = {nid for nid, *_ in self._nc_items}
        groups: Dict[str, List[str]] = defaultdict(list)
        for iid in list(self.dsu.p.keys()):
            groups[self.dsu.find(iid)].append(iid)
        root_has_named: Dict[str, bool] = {}
        for root, items in groups.items():
            pins = [self._pins[i] for i in items if i in self._pins]
            names = []
            for i in items:
                names.extend(self._names.get(i, []))
            root_has_named[root] = bool(pins or names)
            if not pins and not names:
                continue
            if not names and len(pins) > 1 and any(i in nc_ids for i in items) and \
                    len({(p.ref, round(p.x, 2), round(p.y, 2)) for p in pins}) == 1:
                # stacked pins under a no-connect flag: KiCad nets each pin separately as unconnected
                for p in pins:
                    nm = f"unconnected-({p.ref}-{p.name}-Pad{p.pin})"
                    base, k = nm, 1
                    while nm in self.nets:
                        nm = f"{base}_{k}"
                        k += 1
                    self.nets[nm] = Net(nm, [p], [], {p.sheet}, True)
                    self.pin_net[(p.ref, p.pin)] = nm
                continue
            if names:
                names.sort(key=lambda t: (t[0], t[1]))
                name = names[0][1]
                auto = False
            else:
                p0 = sorted(pins, key=lambda p: (p.ref, p.pin))[0]
                name = f"Net-({p0.ref}-Pad{p0.pin})"
                auto = True
            base, n = name, 2
            while name in self.nets:
                name = f"{base}_{n}"
                n += 1
            net = Net(name, pins, sorted({nm for _, nm in names}), {p.sheet for p in pins}, auto)
            self.nets[name] = net
            for p in pins:
                self.pin_net[(p.ref, p.pin)] = name
            power_names = sorted({nm for pr_, nm in names if pr_ <= 2})
            local_names = sorted({nm.rsplit('/', 1)[-1] for pr_, nm in names if pr_ == 3})
            if len(power_names) > 1:
                self.issues.append(Issue("warning", "shorted_global_nets",
                                         f"Global/power nets {', '.join(power_names)} are connected together — this is a short unless intended",
                                         ", ".join(sorted(net.sheets))))
            elif len(local_names) > 1 or (power_names and local_names and local_names[0] not in power_names):
                self.issues.append(Issue("info", "multiple_net_names",
                                         f"Net carries several names: {', '.join(power_names + local_names)} (KiCad picks one)",
                                         ", ".join(sorted(net.sheets))))
        # floating wires
        for inst, wires, wid, _ in getattr(self, "_pending_floating", []):
            seen = set()
            for i in range(len(wires)):
                r = self.dsu.find(wid[i])
                if r in seen:
                    continue
                seen.add(r)
                if not root_has_named.get(r, False):
                    w = wires[i]
                    self.issues.append(Issue("error", "floating_wire",
                                             f"Floating wire group near ({w.x1:.2f}, {w.y1:.2f}) mm is not connected to any pin, label, or sheet pin (ghost wire)",
                                             inst.name_path, w.x1, w.y1))
        # no-connect flags
        group_pins = defaultdict(list)
        for iid, pr in self._pins.items():
            group_pins[self.dsu.find(iid)].append(pr)
        for nid, sheet, x, y in self._nc_items:
            prs = [p for p in group_pins.get(self.dsu.find(nid), []) if not p.ref.startswith("#")]
            if not prs:
                self.issues.append(Issue("warning", "stray_no_connect", "No-connect flag is not attached to any pin", sheet, x, y))
                continue
            for p in prs:
                self._nc_pins.add((p.ref, p.pin))
            locs = {(p.ref, round(p.x, 2), round(p.y, 2)) for p in prs}
            if len(locs) > 1:
                names = ", ".join(sorted({p.label() for p in prs})[:6])
                self.issues.append(Issue("error", "no_connect_connected",
                                         f"No-connect flag sits on a net that connects several pins ({names}) — either remove the flag or the connection", sheet, x, y))
        # pins
        nc = self._nc_pins
        for name, net in self.nets.items():
            real = [p for p in net.pins if not p.ref.startswith("#")]
            if len(net.pins) == 1 and not net.labels:
                p = net.pins[0]
                if p.etype == "no_connect" or (p.ref, p.pin) in nc or p.ref.startswith("#"):
                    continue
                self.issues.append(Issue("warning", "unconnected_pin", f"Pin {p.label()} [{p.etype}] is not connected", p.sheet, p.x, p.y))
            elif len(real) == 1 and net.labels and (real[0].ref, real[0].pin) not in nc:
                p = real[0]
                self.issues.append(Issue("warning", "single_pin_net",
                                         f"Net '{name}' reaches only {p.label()} — the label has no partner elsewhere (typo in label name, or missing connection?)",
                                         p.sheet, p.x, p.y))

    # ------------------------------------------------------------------ queries
    def netlist(self, include_power_symbols=False) -> Dict[str, List[str]]:
        out = {}
        for name, net in sorted(self.nets.items()):
            pins = [p for p in net.pins if include_power_symbols or not p.ref.startswith("#")]
            if pins:
                out[name] = sorted({f"{p.ref}.{p.pin}" for p in pins}, key=_natural)
        return out

    def partitions(self) -> List[frozenset]:
        return [frozenset(v) for v in self.netlist().values()]

    def component_connections(self, ref: str) -> List[dict]:
        rows = []
        for name, net in self.nets.items():
            for p in net.pins:
                if p.ref == ref:
                    others = sorted({o.label() for o in net.pins if not (o.ref == ref and o.pin == p.pin) and not o.ref.startswith("#")})
                    rows.append({"pin": p.pin, "pin_name": p.name, "type": p.etype, "net": name, "connected_to": others})
        return sorted(rows, key=lambda r: _natural(r["pin"]))

    def issues_dicts(self, min_severity="info"):
        order = {"error": 0, "warning": 1, "info": 2}
        lim = order[min_severity]
        return [i.to_dict() for i in sorted(self.issues, key=lambda i: order[i.severity]) if order[i.severity] <= lim]


_vec_re = re.compile(r"^(.*?)\[(\d+)\.\.(\d+)\](.*)$")
_grp_re = re.compile(r"^(.*?)\{([^}]*)\}$")


def expand_bus(name: str, aliases: Optional[Dict[str, List[str]]] = None) -> List[str]:
    """Expand KiCad bus names into member net names.

    'D[0..7]' -> D0..D7;  '{SDA SCL}' -> SDA, SCL;  'I2C{SDA SCL}' -> I2C.SDA, I2C.SCL;
    'USB_C{USB}' with alias USB=(D_P D_N) -> USB_C.D_P, USB_C.D_N;  bare alias 'USB' -> D_P, D_N.
    """
    aliases = aliases or {}
    m = _vec_re.match(name)
    if m and _split_group(name) is None:
        pre, a, b, post = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        lo, hi = min(a, b), max(a, b)
        if hi - lo > 1024:
            return []
        return [f"{pre}{i}{post}" for i in range(lo, hi + 1)]
    g = _split_group(name)
    if g:
        pre, body = g
        out = []
        for mem in re.split(r"[\s,]+", body.strip()):
            if mem in aliases:
                sub = []
                for am in aliases[mem]:
                    sub.extend(expand_bus(am, aliases) or [am])
            else:
                sub = expand_bus(mem, aliases) or [mem]
            out.extend(f"{pre}.{x}" if pre else x for x in sub)
        return out
    if name in aliases:
        out = []
        for am in aliases[name]:
            out.extend(expand_bus(am, aliases) or [am])
        return out
    return []


_ESC = {"{slash}": "/", "{backslash}": "\\", "{lt}": "<", "{gt}": ">", "{colon}": ":", "{dblquote}": '"',
        "{space}": " ", "{tab}": "\t", "{comma}": ",", "{return}": "\n", "{brace_open}": "{", "{brace_close}": "}"}


def unescape_label(s: str) -> str:
    for k, v in _ESC.items():
        if k in s:
            s = s.replace(k, v)
    return s


def _unesc_name(s: str) -> str:
    return unescape_label(s) if "{" in s else s


def _split_group(name: str):
    """Split 'PREFIX{members}' where the final brace group is a bus group (not _{sub}/^{sup}/~{bar} markup)."""
    if not name.endswith("}"):
        return None
    depth = 0
    for i in range(len(name) - 1, -1, -1):
        c = name[i]
        if c == "}":
            depth += 1
        elif c == "{":
            depth -= 1
            if depth == 0:
                if i > 0 and name[i - 1] in "_^~$":
                    return None
                body = name[i + 1:-1]
                if body in ("slash", "dblquote", "backslash", "lt", "gt", "space", "tab", "return", "colon", "comma"):
                    return None
                return name[:i], body
    return None


def _member_suffix(name: str) -> str:
    return name.split(".", 1)[1] if "." in name else name


def _natural(s):
    import re
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]
