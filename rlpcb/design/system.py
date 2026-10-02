"""Multi-board systems: boards (KiCad projects) joined by harnesses between connectors.

system.json:
{
  "name": "Printer",
  "boards":    {"main": "main/main.kicad_pro", "engine": "engine/engine.kicad_pro"},
  "harnesses": [{"id": "H1", "a": {"board": "main", "ref": "J5"}, "b": {"board": "engine", "ref": "J1"},
                 "mapping": "straight" | "reversed" | {"1": "1", "2": "3", ...}, "pin_current_a": 1.0, "cable": "..."}],
  "supplies":  [{"board": "psu", "net": "+24V", "capacity_a": 5.0, "local_load_a": 0.5}],
  "acknowledged": [{"rule": "pin_current", "where": "H1", "match": "VBAT", "reason": "..."}]
}

system_check walks every harness pin pair and flags: ground↔signal, power↔signal, voltage mismatch, TX↔TX / RX↔RX,
two push-pull outputs facing each other, a pin used on one side but open on the other, pin-count mismatch, per-pin
current above the connector rating, and rails whose total load exceeds the supply.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

from .checks import net_voltage
from .verify import classify_net

SYSTEM_FILE = "system.json"


def _path(folder: str) -> str:
    return folder if folder.endswith(".json") else os.path.join(folder, SYSTEM_FILE)


def load(folder: str) -> Dict:
    p = _path(folder)
    if not os.path.exists(p):
        raise FileNotFoundError(f"No {SYSTEM_FILE} in {folder}; create one with system_create")
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f)


def save(folder: str, data: Dict) -> str:
    p = _path(folder)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return p


def create(folder: str, name: str) -> Dict:
    data = {"name": name, "boards": {}, "harnesses": [], "supplies": []}
    save(folder, data)
    return data


def _resolve_board(folder: str, rel: str) -> str:
    p = rel if os.path.isabs(rel) else os.path.join(os.path.dirname(_path(folder)), rel)
    if os.path.isdir(p):
        pros = [f for f in os.listdir(p) if f.endswith(".kicad_pro")]
        if pros:
            p = os.path.join(p, pros[0])
    return os.path.abspath(p)


class BoardView:
    """Pin → net for one board, from its RL PCB plan or (if none) from its schematic."""

    def __init__(self, pro_path: str, pin_lookup: Callable[[str], List[dict]]):
        from .plan import DesignPlan
        self.pro = pro_path
        d = os.path.dirname(pro_path)
        name = os.path.splitext(os.path.basename(pro_path))[0]
        plan = DesignPlan.load_or_new(d, name)
        self.source = "plan"
        if not plan.components:
            sch = os.path.join(d, name + ".kicad_sch")
            if os.path.exists(sch):
                from ..kicad.schematic import Hierarchy
                from .review import plan_from_schematic
                plan = plan_from_schematic(Hierarchy(sch))
                self.source = "schematic"
        self.plan = plan
        self.owner = plan.node_net()
        self.nets = {n.name: n for n in plan.nets}
        self.comps = {c.ref: c for c in plan.components}
        self.nc = set(plan.no_connect)
        self.pin_lookup = pin_lookup

    def pins(self, ref: str) -> List[str]:
        c = self.comps.get(ref)
        if not c:
            return []
        nums = [p["number"] for p in (self.pin_lookup(c.lib_id) or [])]
        if not nums:
            nums = sorted({k.split(".", 1)[1] for k in self.owner if k.split(".", 1)[0] == ref} | {
                k.split(".", 1)[1] for k in self.nc if k.split(".", 1)[0] == ref}, key=lambda x: (len(x), x))
        return [n for n in nums if re.fullmatch(r"\d+", n)]  # numbered signal pins (skip MP/shield names)

    def pin_info(self, ref: str, pin: str) -> Dict:
        node = f"{ref}.{pin}"
        net = self.owner.get(node)
        info = {"node": node, "net": net, "nc": node in self.nc}
        if net:
            n = self.nets[net]
            cls = classify_net(net)
            info.update(kind=("ground" if cls == "ground" else "power" if (cls == "power" or (n.net_class or "") == "power")
                              else "signal"),
                        voltage=net_voltage(n), current=n.current_a,
                        drivers=self._drivers(net, ref))
        else:
            info["kind"] = "open"
        return info

    def _drivers(self, net: str, conn_ref: str) -> List[str]:
        out = []
        for node in self.nets[net].nodes:
            r, p = node.split(".", 1)
            if r == conn_ref or r not in self.comps:
                continue
            for pd in self.pin_lookup(self.comps[r].lib_id) or []:
                if pd["number"] == p and pd["type"] in ("output", "power_out"):
                    out.append(f"{node} ({pd.get('name', '')})")
        return out


def _base(name: Optional[str]) -> str:
    return re.sub(r"^.*/", "", name or "").upper()


def _dir(name: str) -> Optional[str]:
    """Direction of a serial line from its name: the last TX/RX-like token wins ('RX_TX' = the receiver's TX line)."""
    toks = [t for t in re.split(r"[_/\-\s]", _base(name)) if t]
    for t in reversed(toks):
        t = re.sub(r"\d+$", "", t)
        if t in ("TX", "TXD", "TXO"):
            return "TX"
        if t in ("RX", "RXD", "RXI"):
            return "RX"
    return None


def _mapping(h: Dict, pins_a: List[str], pins_b: List[str]) -> List[Tuple[str, str]]:
    m = h.get("mapping", "straight")
    if isinstance(m, dict):
        return [(str(a), str(b)) for a, b in m.items()]
    if m == "reversed":
        return list(zip(pins_a, list(reversed(pins_b))))
    return list(zip(pins_a, pins_b))


def check(folder: str, pin_lookup: Callable[[str], List[dict]]) -> Dict:
    data = load(folder)
    findings: List[Dict] = []
    views: Dict[str, BoardView] = {}
    for bname, rel in data.get("boards", {}).items():
        p = _resolve_board(folder, rel)
        if not os.path.exists(p):
            findings.append({"severity": "error", "rule": "board_missing", "message": f"Board '{bname}': {p} not found"})
            continue
        views[bname] = BoardView(p, pin_lookup)

    def F(sev, rule, msg, where):
        findings.append({"severity": sev, "rule": rule, "message": msg, "where": where})

    rail_load = defaultdict(float)        # (board, net) -> current drawn through harnesses
    pin_rows = []
    for h in data.get("harnesses", []):
        hid = h.get("id") or f"{h['a']['board']}.{h['a']['ref']}-{h['b']['board']}.{h['b']['ref']}"
        va, vb = views.get(h["a"]["board"]), views.get(h["b"]["board"])
        if not va or not vb:
            continue
        ra, rb = h["a"]["ref"], h["b"]["ref"]
        pa, pb = va.pins(ra), vb.pins(rb)
        if not pa or not pb:
            F("error", "connector_missing", f"{hid}: connector {ra if not pa else rb} not found on its board", hid)
            continue
        if isinstance(h.get("mapping", "straight"), str) and len(pa) != len(pb):
            F("error", "pin_count", f"{hid}: {h['a']['board']}.{ra} has {len(pa)} pins but {h['b']['board']}.{rb} has {len(pb)}", hid)
        pin_i = float(h.get("pin_current_a") or 1.0)
        per_net_pins = defaultdict(int)
        pairs = _mapping(h, pa, pb)
        infos = [(va.pin_info(ra, x), vb.pin_info(rb, y)) for x, y in pairs]
        for ia, ib in infos:
            if ia.get("net"):
                per_net_pins[("a", ia["net"])] += 1
            if ib.get("net"):
                per_net_pins[("b", ib["net"])] += 1
        for (x, y), (ia, ib) in zip(pairs, infos):
            where = f"{hid} pin {x}↔{y} ({h['a']['board']}.{ia['node']} ↔ {h['b']['board']}.{ib['node']})"
            row = {"harness": hid, "a": f"{h['a']['board']}.{ia['node']}", "a_net": ia.get("net"),
                   "b": f"{h['b']['board']}.{ib['node']}", "b_net": ib.get("net"), "status": "ok"}
            ka, kb = ia["kind"], ib["kind"]
            problem = None
            if ka == "open" and kb == "open":
                row["status"] = "unused"
            elif (ka == "open") != (kb == "open"):
                used = ia if kb == "open" else ib
                problem = ("warning", "open_pin", f"{where}: '{used['net']}' on one side meets an unconnected pin on the other")
            elif (ka == "ground") != (kb == "ground"):
                problem = ("error", "ground_mismatch", f"{where}: ground '{ia['net'] if ka == 'ground' else ib['net']}' meets "
                                                      f"{'power' if 'power' in (ka, kb) else 'signal'} '{ib['net'] if ka == 'ground' else ia['net']}'")
            elif ka == "power" and kb == "power":
                a_v, b_v = ia.get("voltage"), ib.get("voltage")
                # which side supplies? the side with a regulator/source driving it, or a declared supply
                declared = {(x["board"], x["net"]) for x in data.get("supplies", [])}
                src_a = bool(ia.get("drivers")) or (h["a"]["board"], ia["net"]) in declared
                src_b = bool(ib.get("drivers")) or (h["b"]["board"], ib["net"]) in declared
                if a_v and b_v and abs(a_v - b_v) > 0.1 * max(a_v, b_v):
                    if src_a != src_b:
                        # a net's voltage_v on the receiving board is its rating (max input); on the supplying board
                        # it is what arrives. Lower than the rating is fine; higher is not.
                        sv, lv = (a_v, b_v) if src_a else (b_v, a_v)
                        if sv > lv * 1.02:
                            problem = ("error", "voltage_mismatch", f"{where}: supply {sv:g} V exceeds the receiving "
                                                                    f"side's {lv:g} V rating")
                        else:
                            row["status"] = f"ok (supplied {sv:g} V, rated {lv:g} V)"
                    else:
                        problem = ("error", "voltage_mismatch", f"{where}: {ia['net']} ({a_v:g} V) meets {ib['net']} ({b_v:g} V)")
                if src_a and src_b:
                    problem = problem or ("warning", "two_supplies", f"{where}: both boards drive {ia['net']} / {ib['net']} "
                                                                     f"({ia['drivers'][:1]} and {ib['drivers'][:1]})")
                load_side, lside = (ib, "b") if src_a else (ia, "a")
                sup_side = ia if lside == "b" else ib
                if load_side.get("current"):
                    n_pins = per_net_pins[(lside, load_side["net"])] or 1
                    rail_load[(h["a"]["board"] if lside == "b" else h["b"]["board"], sup_side["net"])] += \
                        load_side["current"] / n_pins
                    row["current_a"] = round(load_side["current"] / n_pins, 3)
            elif "power" in (ka, kb):
                pw, sg = (ia, ib) if ka == "power" else (ib, ia)
                problem = ("error", "power_to_signal", f"{where}: power '{pw['net']}' meets signal '{sg['net']}'")
            else:
                da, db = _dir(ia["net"]), _dir(ib["net"])
                if da and db and da == db:
                    problem = ("error", "uart_direction", f"{where}: {ia['net']} ↔ {ib['net']} — {da} must meet "
                                                          f"{'RX' if da == 'TX' else 'TX'}: cross the pair")
                elif ia.get("drivers") and ib.get("drivers"):
                    problem = ("error", "driver_conflict", f"{where}: outputs on both sides ({ia['drivers'][0]} and "
                                                          f"{ib['drivers'][0]})")
                elif _base(ia["net"]) != _base(ib["net"]):
                    row["status"] = "check names"
            # per-pin current
            # a power pin carries the load side's current (the supply side's current_a is its rail rating)
            if ka == "power" and kb == "power" and "current_a" in row:
                checks_i = [(row["current_a"], ia if ia.get("current") else ib)]
            else:
                checks_i = [(inf["current"] / (per_net_pins[(side, inf["net"])] or 1), inf)
                            for inf, side in ((ia, "a"), (ib, "b")) if inf.get("current") and inf.get("net")]
            for per_pin, inf in checks_i:
                if True:
                    if per_pin > pin_i:
                        problem = problem or ("warning", "pin_current", f"{where}: {inf['net']} carries ≈{per_pin:.2f} A "
                                                                        f"per pin; connector rated {pin_i:g} A per pin — "
                                                                        "use more pins or a bigger connector")
            if problem:
                F(problem[0], problem[1], problem[2], hid)
                row["status"] = problem[1]
            pin_rows.append(row)

    # supply capacity
    for sup in data.get("supplies", []):
        v = views.get(sup["board"])
        if not v:
            continue
        net = sup["net"]
        # the supplying board's own draw: declared local_load_a, else its net's current_a (which may be the rail
        # rating rather than the load — declare local_load_a to be exact)
        if sup.get("local_load_a") is not None:
            own = float(sup["local_load_a"])
        else:
            own = (v.nets.get(net).current_a or 0) if v.nets.get(net) else 0
        remote = sum(a for (b, n), a in rail_load.items() if b == sup["board"] and n == net)
        total = own + remote
        if total > sup.get("capacity_a", 0):
            F("error", "supply_capacity", f"{sup['board']}.{net}: load ≈{total:.2f} A (local {own:g} A + other boards "
                                          f"{remote:.2f} A) exceeds the supply's {sup['capacity_a']:g} A", sup["board"])
        elif total > 0.8 * sup.get("capacity_a", 0):
            F("warning", "supply_capacity", f"{sup['board']}.{net}: load ≈{total:.2f} A is over 80 % of {sup['capacity_a']:g} A",
              sup["board"])
    # acknowledged findings: {"rule": ..., "where": ..., "match": "<text in message>", "reason": ...}
    for f in findings:
        for ack in data.get("acknowledged", []):
            if ack.get("rule") == f["rule"] and ack.get("where", f["where"]) == f["where"] and \
                    ack.get("match", "") in f["message"]:
                f["severity"], f["acknowledged"] = "info", ack.get("reason", "")
    by = defaultdict(int)
    for f in findings:
        by[f["severity"]] += 1
    return {"system": data.get("name"), "boards": {k: {"project": v.pro, "source": v.source} for k, v in views.items()},
            "summary": dict(by), "findings": findings, "pins": pin_rows}
