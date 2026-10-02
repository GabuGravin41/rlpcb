"""Wiring guidance and verification of a hand-drawn schematic against the design plan."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ..kicad.connectivity import Connectivity
from ..kicad.schematic import Hierarchy
from .plan import DesignPlan

GROUND_RE = re.compile(r"^(A|D|P|CHASSIS|EARTH|SIG|PWR)?GND[A-Z0-9_]*$|^VSS[A-Z0-9_]*$|^0V$", re.I)
POWER_RE = re.compile(r"^(\+|-)?\d+(V\d*|\.\d+V|V)[A-Z0-9_]*$|^V(CC|DD|EE|IN|BUS|BAT|SYS|MAIN|REF)[A-Z0-9_]*$|^\+?V[0-9_]+", re.I)


def _nat(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def classify_net(name: str, declared: str = "") -> str:
    if declared:
        return declared
    base = name.split("/")[-1]
    if GROUND_RE.match(base):
        return "ground"
    if POWER_RE.match(base):
        return "power"
    return "signal"


class DesignState:
    """The drawn schematic seen through the lens of the plan."""

    def __init__(self, plan: DesignPlan, hier: Hierarchy):
        self.plan = plan
        self.hier = hier
        self.conn = Connectivity(hier)
        self.pin_net: Dict[str, str] = {f"{r}.{p}": n for (r, p), n in self.conn.pin_net.items()}
        self.pin_pos: Dict[str, Tuple[float, float, str, str]] = {}
        for net in self.conn.nets.values():
            for p in net.pins:
                self.pin_pos[f"{p.ref}.{p.pin}"] = (p.x, p.y, p.sheet, p.name)
        self.placed_refs = {ref for _, _, ref, _ in hier.iter_symbols()}
        self.placed_units: Dict[str, set] = defaultdict(set)
        self._lib_by_ref = {}
        for inst, sym, ref, unit in hier.iter_symbols():
            self.placed_units[ref].add(unit)
            self._lib_by_ref.setdefault(ref, inst.sch.lib_for(sym))
        self.net_members: Dict[str, List[str]] = defaultdict(list)
        for k, n in self.pin_net.items():
            self.net_members[n].append(k)

    # ------------------------------------------------------------------ verify
    def verify(self) -> dict:
        plan = self.plan
        errors, warnings, done_nets = [], [], []
        plan_owner = plan.node_net()
        total_links = 0
        done_links = 0
        per_net = []
        not_placed = sorted({c.ref for c in plan.components} - self.placed_refs, key=_nat)
        for net in plan.nets:
            nodes = [n for n in net.nodes if n.split(".")[0] in self.placed_refs]
            if len(net.nodes) < 2:
                continue
            groups: Dict[str, List[str]] = defaultdict(list)
            missing_pins = []
            for n in nodes:
                an = self.pin_net.get(n)
                if an is None:
                    missing_pins.append(n)
                else:
                    groups[an].append(n)
            links = len(net.nodes) - 1
            total_links += links
            main = max(groups.values(), key=len) if groups else []
            # a group of size 1 means the pin is on its own net, i.e. unconnected (unless labeled)
            satisfied = max(0, len(main) - 1)
            done_links += satisfied
            status = "complete" if satisfied == links else ("partial" if satisfied else "not started")
            entry = {"net": net.name, "status": status, "connected": f"{satisfied}/{links}"}
            if status != "complete":
                pending = [n for n in net.nodes if n not in main]
                entry["still_to_connect"] = [self._pin_desc(n) for n in pending]
                if len(main) > 1:
                    entry["already_joined"] = [self._pin_desc(n) for n in main]
            per_net.append(entry)
            if status == "complete":
                done_nets.append(net.name)
            for n in missing_pins:
                if n.split(".")[0] in self.placed_refs:
                    unit = self._unit_of_pin(n)
                    if unit and unit not in self.placed_units.get(n.split(".")[0], set()):
                        warnings.append({"kind": "unit_not_placed",
                                         "message": f"{n} belongs to unit {unit} of {n.split('.')[0]}, which is not placed yet"})
                    else:
                        errors.append({"kind": "pin_not_found",
                                       "message": f"{n} is in the plan but that pin does not exist on the placed symbol (wrong symbol?)"})
        # shorts and extras: examine every actual net that contains planned pins
        for an, members in self.net_members.items():
            planned = defaultdict(list)
            extras = []
            for m in members:
                if m.startswith("#"):
                    continue
                pn = plan_owner.get(m)
                if pn:
                    planned[pn].append(m)
                elif m.split(".")[0] in {c.ref for c in plan.components}:
                    extras.append(m)
            if len(planned) > 1:
                parts = "; ".join(f"{k}: {', '.join(v[:4])}" for k, v in planned.items())
                errors.append({"kind": "short", "nets": sorted(planned),
                               "message": f"Planned nets {', '.join(sorted(planned))} are connected together in the drawing (drawn net '{an}'). {parts}"})
            if extras and len(members) > 1:
                for e in extras:
                    if e in plan.no_connect:
                        errors.append({"kind": "no_connect_wired", "message": f"{self._pin_desc(e)} should be left unconnected but is wired to '{an}'"})
                    else:
                        warnings.append({"kind": "unplanned_connection",
                                         "message": f"{self._pin_desc(e)} is wired to '{an}' but the plan does not connect it"})
        # component attribute mismatches
        mism = []
        comps = self.hier.components()
        for c in plan.components:
            got = comps.get(c.ref)
            if not got:
                continue
            if c.lib_id and got["lib_id"] != c.lib_id and got["lib_id"].split(":")[-1] != c.lib_id.split(":")[-1]:
                mism.append(f"{c.ref}: plan symbol {c.lib_id}, drawn {got['lib_id']}")
            if c.value and got["value"] != c.value:
                mism.append(f"{c.ref}: plan value '{c.value}', drawn '{got['value']}'")
            if c.footprint and got["footprint"] and got["footprint"] != c.footprint:
                mism.append(f"{c.ref}: plan footprint {c.footprint}, drawn {got['footprint']}")
            if c.footprint and not got["footprint"]:
                mism.append(f"{c.ref}: no footprint assigned (plan: {c.footprint})")
        unplanned_parts = sorted(set(comps) - {c.ref for c in plan.components}, key=_nat)
        geometry = [i for i in self.conn.issues_dicts("warning") if i["kind"] in
                    ("dangling_wire_end", "floating_wire", "t_without_junction", "off_grid_pin", "dangling_label",
                     "no_connect_connected", "shorted_global_nets")]
        pct = round(100.0 * done_links / total_links, 1) if total_links else 0.0
        return {
            "progress_percent": pct,
            "connections_done": done_links,
            "connections_planned": total_links,
            "nets_complete": len(done_nets),
            "nets_total": len([n for n in plan.nets if len(n.nodes) > 1]),
            "not_placed": not_placed,
            "errors": errors,
            "warnings": warnings,
            "attribute_mismatches": mism,
            "parts_not_in_plan": unplanned_parts,
            "drawing_problems": geometry,
            "nets": sorted(per_net, key=lambda e: (e["status"] == "complete", e["net"])),
        }

    def _unit_of_pin(self, node: str) -> int:
        ref, pin = node.split(".", 1)
        lib = self._lib_by_ref.get(ref)
        if lib is None:
            return 0
        for p in lib.pins:
            if p.number == pin:
                return p.unit
        return 0

    def _pin_desc(self, node: str) -> str:
        pos = self.pin_pos.get(node)
        comp = self.plan.comp(node.split(".")[0])
        if pos:
            x, y, sheet, name = pos
            nm = f" ({name})" if name and name not in ("~", node.split(".")[1]) else ""
            sh = f" on sheet {sheet}" if sheet not in ("/", "") else ""
            return f"{node}{nm} at ({x:.2f}, {y:.2f}){sh}"
        if comp is None:
            return node
        return f"{node} (not placed yet)"

    # ------------------------------------------------------------------ guide
    def wiring_guide(self, block: Optional[str] = None, net_filter: Optional[str] = None,
                     long_wire_mm: float = 60.0, power_symbol=None) -> dict:
        """Ordered wiring steps: shortest wiring (minimum spanning tree over pin positions),
        power/ground via power symbols, far-apart pins via net labels. Already-done links are marked."""
        plan = self.plan
        steps = []
        refs_in_block = {c.ref for c in plan.components if not block or c.block == block}
        order = {"power": 0, "ground": 1}
        nets = [n for n in plan.nets if len(n.nodes) >= 1]
        nets.sort(key=lambda n: (order.get(classify_net(n.name, n.net_class), 2), n.name))
        for net in nets:
            if net_filter and not re.search(net_filter, net.name, re.I):
                continue
            nodes = [x for x in net.nodes if x.split(".")[0] in refs_in_block]
            if not nodes:
                continue
            kind = classify_net(net.name, net.net_class)
            placed = [x for x in nodes if x in self.pin_pos]
            unplaced = [x for x in nodes if x not in self.pin_pos]
            item = {"net": net.name, "class": kind, "notes": net.notes}
            sheets = {self.pin_pos[x][2] for x in net.nodes if x in self.pin_pos}
            if kind in ("power", "ground") and (len(net.nodes) > 2 or len(sheets) > 1):
                done = [x for x in placed if self._has_power_name(x, net.name)]
                todo = [x for x in placed if x not in done]
                ps = power_symbol(net.name) if power_symbol else None
                if ps:
                    item["method"] = "power symbols"
                    item["instruction"] = (f"Press P (Add Power), pick {ps}, and drop one on the end of each pin below. Each "
                                           "symbol must touch the pin end exactly (the little pin-end circle disappears when it "
                                           "connects). A short wire stub from the pin to the symbol is fine.")
                else:
                    item["method"] = "global labels"
                    item["instruction"] = (f"There is no stock power symbol named '{net.name}'. Press Ctrl+L (global label), "
                                           f"type {net.name}, and attach one to the end of each pin below (or create a power "
                                           f"symbol with that name in your project library if you'll reuse it).")
                item["pins"] = [self._pin_desc(x) for x in todo]
                item["already_done"] = [x for x in done]
            else:
                links = _mst([(x, self.pin_pos[x][:2]) for x in placed])
                item["method"] = "wires"
                seq = []
                for a, b, d in links:
                    ok = self.pin_net.get(a) is not None and self.pin_net.get(a) == self.pin_net.get(b)
                    same_sheet = self.pin_pos[a][2] == self.pin_pos[b][2]
                    how = "wire" if d <= long_wire_mm and same_sheet else "label"
                    txt = (f"Draw a wire from {self._pin_desc(a)} to {self._pin_desc(b)}" if how == "wire" else
                           f"Put a net label '{net.name}' (press L) on {self._pin_desc(a)} and another on {self._pin_desc(b)}"
                           + (" — they are on different sheets, use a global or hierarchical label" if not same_sheet else
                              f" — they are {d:.0f} mm apart, a label keeps the sheet readable"))
                    seq.append({"done": ok, "step": txt, "length_mm": round(d, 1)})
                item["steps"] = seq
                if len(sheets) > 1:
                    item["cross_sheet"] = (f"'{net.name}' spans sheets {', '.join(sorted(sheets))}: on each sheet wire its pins "
                                           f"together as above and add one global label '{net.name}' (Ctrl+L) on that group.")
            if unplaced:
                item["waiting_for_parts"] = unplaced
            steps.append(item)
        tips = [
            "Hover over a pin end and press W to start a wire exactly on it; click once on the other pin end to finish. "
            "Double-click or press Esc to stop.",
            "A wire only connects at pin ENDS (the small circle). Crossing a pin or wire in the middle does nothing.",
            "A wire ending on the middle of another wire needs a junction dot to connect (KiCad adds one automatically when you "
            "end on a wire, but not when you move things later).",
            "After wiring a block, ask me to verify — I read the file and list anything missing, shorted, or floating.",
        ]
        return {"block": block or "all", "nets": steps, "tips": tips}

    def _has_power_name(self, node: str, name: str) -> bool:
        an = self.pin_net.get(node, "")
        if an.split("/")[-1] == name:
            return True
        members = self.net_members.get(an, [])
        return len(members) > 1 and an.split("/")[-1].upper() == name.upper()


def _mst(points: List[Tuple[str, Tuple[float, float]]]):
    """Prim's minimum spanning tree over pin positions -> [(a, b, dist)] in build order."""
    if len(points) < 2:
        return []
    names = [p[0] for p in points]
    pos = {p[0]: p[1] for p in points}
    in_tree = {names[0]}
    edges = []
    while len(in_tree) < len(names):
        best = None
        for a in in_tree:
            for b in names:
                if b in in_tree:
                    continue
                (x1, y1), (x2, y2) = pos[a], pos[b]
                d = abs(x1 - x2) + abs(y1 - y2)  # orthogonal wiring length
                if best is None or d < best[2]:
                    best = (a, b, d)
        edges.append(best)
        in_tree.add(best[1])
    return edges
