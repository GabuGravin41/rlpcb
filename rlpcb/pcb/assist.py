"""PCB assistance: stackup advice, net classes/rules from the plan, placement suggestions, file-based moves."""
from __future__ import annotations

import json
import math
import os
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ..design.plan import DesignPlan
from ..design.sch_writer import backup, lock_file_for
from ..design.verify import classify_net
from ..kicad.sexpr import Node, QStr, dump, fmt_num, parse
from .board import Board, BFootprint, rot

# ---------------------------------------------------------------- stackup advice


def advise_stackup(max_pins_bga: int = 0, bga_pitch_mm: float = 0.0, high_speed: List[str] = (),
                   power_rails: int = 1, max_current_a: float = 1.0, board_area_cm2: float = 50.0,
                   component_count: int = 50, mains_or_hv: bool = False, rf: bool = False,
                   budget: str = "low") -> Dict:
    """Rule-of-thumb layer count & stackup. high_speed: e.g. ['USB2','USB3','ETH1G','PCIE3','DDR4','HDMI','MIPI','LVDS']."""
    hs = {h.upper() for h in high_speed}
    reasons = []
    layers = 2
    density = component_count / max(board_area_cm2, 1)
    if density > 1.5:
        layers = max(layers, 4)
        reasons.append(f"component density {density:.1f}/cm² — 2 layers will be very hard to route with a solid ground")
    if hs & {"USB2", "ETH100", "CAN", "RS485", "SPI_FAST", "SDIO"} or rf:
        layers = max(layers, 4)
        reasons.append("controlled-impedance / fast edges need an unbroken reference plane directly under signals → 4 layers")
    if hs & {"USB3", "ETH1G", "HDMI", "PCIE2", "PCIE3", "MIPI", "LVDS", "SATA", "DDR3", "DDR4", "LPDDR4", "PCIE4", "PCIE5", "10G"}:
        layers = max(layers, 6)
        reasons.append("multi-gigabit / DDR interfaces want stripline layers and several plane references → 6+ layers")
    if hs & {"DDR4", "LPDDR4", "PCIE4", "PCIE5", "10G", "25G"}:
        layers = max(layers, 8)
        reasons.append("DDR4/LPDDR4 or PCIe Gen4+ routing typically needs 8+ layers with back-drilled or blind vias")
    if power_rails >= 8 or (power_rails >= 4 and max_current_a > 10):
        layers = max(layers, 6 if power_rails < 12 else 8)
        reasons.append(f"{power_rails} power rails at up to {max_current_a:g} A: more than one power plane layer → 6+ layers")
    elif power_rails >= 3 and layers >= 4:
        reasons.append(f"{power_rails} power rails: one power layer with split pours per rail (keep splits out from under "
                       "signals that reference that layer)")
    if bga_pitch_mm:
        rows = int(math.sqrt(max_pins_bga)) if max_pins_bga else 0
        ring = math.ceil(rows / 2) if rows else 0
        if bga_pitch_mm >= 1.0:
            need = 4 if ring <= 4 else 6 if ring <= 8 else 8
        elif bga_pitch_mm >= 0.8:
            need = 4 if ring <= 3 else 6 if ring <= 6 else 10
        elif bga_pitch_mm >= 0.65:
            need = 6 if ring <= 5 else 10
        else:
            need = 8
        if max_pins_bga > 1500:
            need = max(need, 12)
        if max_pins_bga > 3000:
            need = max(need, 16)
        layers = max(layers, need)
        reasons.append(f"BGA {max_pins_bga} balls at {bga_pitch_mm} mm pitch: ~{ring} escape rings → ≥{need} layers "
                       "(roughly two signal rows escape per routing layer with dog-bone fanout)")
        if bga_pitch_mm < 0.65:
            reasons.append("pitch < 0.65 mm needs via-in-pad (filled & capped) or laser microvias — HDI process")
    if max_current_a > 5:
        reasons.append(f"{max_current_a} A: use 2 oz outer copper or dedicated planes/pours for the high-current path")
    if mains_or_hv:
        reasons.append("mains/HV: keep primary side on outer layers with slots for creepage; avoid planes under the isolation barrier")
    stack = STACKUPS.get(layers) or STACKUPS[max(k for k in STACKUPS if k <= layers)]
    fab = ("standard prototype fab (JLCPCB/PCBWay-class) OK" if layers <= 6 and (not bga_pitch_mm or bga_pitch_mm >= 0.65)
           else "needs a fab with HDI / impedance control / tighter tolerances; expect higher cost and lead time")
    return {"recommended_copper_layers": layers, "reasons": reasons or ["simple board: 2 layers with a ground pour on the bottom"],
            "stackup": stack, "fabrication": fab,
            "kicad_steps": ["Board Setup → Board Stackup → Physical Stackup: set copper layer count and dielectric thicknesses "
                            "to your fab's standard stackup (ask them for εr and thickness)",
                            "Board Setup → Net Classes: create classes (Power, HighSpeed, 90R_USB, 100R_DIFF...) and assign patterns",
                            "Board Setup → Constraints: set min clearance/track/via to the fab capability (e.g. 0.127/0.127/0.3 mm drill for JLC standard)",
                            "Add GND zones on the plane layers (Place → Add Filled Zone, Ctrl+Shift+Z) and refill all zones with B"]}


STACKUPS = {
    2: [{"layer": "F.Cu", "use": "signals + components, ground pour in empty areas"},
        {"layer": "core ~1.5 mm"},
        {"layer": "B.Cu", "use": "mostly solid GND pour; short jumpers only, route across not along the pour"}],
    4: [{"layer": "F.Cu", "use": "signals/components (microstrip over L2)"},
        {"layer": "prepreg ~0.1–0.2 mm"},
        {"layer": "In1.Cu", "use": "solid GND plane — never split"},
        {"layer": "core ~1.0–1.2 mm"},
        {"layer": "In2.Cu", "use": "power plane(s) / pours, occasional slow signals"},
        {"layer": "prepreg ~0.1–0.2 mm"},
        {"layer": "B.Cu", "use": "signals/components (reference is the power plane — stitch caps if fast signals cross)"}],
    6: [{"layer": "F.Cu", "use": "signals (microstrip over GND)"},
        {"layer": "In1.Cu", "use": "GND"},
        {"layer": "In2.Cu", "use": "high-speed signals (stripline between GND and PWR/GND)"},
        {"layer": "In3.Cu", "use": "power planes"},
        {"layer": "In4.Cu", "use": "GND"},
        {"layer": "B.Cu", "use": "signals"}],
    8: [{"layer": "F.Cu", "use": "signals"}, {"layer": "In1.Cu", "use": "GND"},
        {"layer": "In2.Cu", "use": "signals (stripline)"}, {"layer": "In3.Cu", "use": "GND"},
        {"layer": "In4.Cu", "use": "power"}, {"layer": "In5.Cu", "use": "signals (stripline)"},
        {"layer": "In6.Cu", "use": "GND"}, {"layer": "B.Cu", "use": "signals"}],
    10: [{"layer": "F.Cu", "use": "signals/fanout"}, {"layer": "In1.Cu", "use": "GND"},
         {"layer": "In2.Cu", "use": "signals"}, {"layer": "In3.Cu", "use": "signals (orthogonal to In2)"},
         {"layer": "In4.Cu", "use": "GND"}, {"layer": "In5.Cu", "use": "power (core rail)"},
         {"layer": "In6.Cu", "use": "signals"}, {"layer": "In7.Cu", "use": "GND"},
         {"layer": "In8.Cu", "use": "power / signals"}, {"layer": "B.Cu", "use": "signals/decoupling"}],
    12: [{"layer": "F.Cu"}, {"layer": "In1.Cu", "use": "GND"}, {"layer": "In2.Cu", "use": "signals"},
         {"layer": "In3.Cu", "use": "GND"}, {"layer": "In4.Cu", "use": "signals"}, {"layer": "In5.Cu", "use": "power"},
         {"layer": "In6.Cu", "use": "power"}, {"layer": "In7.Cu", "use": "signals"}, {"layer": "In8.Cu", "use": "GND"},
         {"layer": "In9.Cu", "use": "signals"}, {"layer": "In10.Cu", "use": "GND"}, {"layer": "B.Cu"}],
    16: [{"layer": "F.Cu", "use": "BGA fanout (via-in-pad)"}, {"layer": "In1.Cu", "use": "GND"},
         {"layer": "In2..In5", "use": "SerDes/PCIe stripline pairs, each between GND planes"},
         {"layer": "In6..In9", "use": "multiphase VRM core-rail planes (heavy copper) + GND"},
         {"layer": "In10..In13", "use": "control/low-speed signals + GND"}, {"layer": "In14.Cu", "use": "GND"},
         {"layer": "B.Cu", "use": "decoupling under the BGA"}],
}


# ---------------------------------------------------------------- net classes
NETCLASS_DEFAULTS = {
    "Power": {"track_width": 0.5, "clearance": 0.2, "via_diameter": 0.8, "via_drill": 0.4},
    "HighCurrent": {"track_width": 1.5, "clearance": 0.25, "via_diameter": 1.0, "via_drill": 0.5},
    "Ground": {"track_width": 0.5, "clearance": 0.2, "via_diameter": 0.8, "via_drill": 0.4},
    "HighSpeed": {"track_width": 0.2, "clearance": 0.2, "via_diameter": 0.6, "via_drill": 0.3},
    "Diff90": {"track_width": 0.2, "clearance": 0.2, "diff_pair_width": 0.2, "diff_pair_gap": 0.15, "via_diameter": 0.6, "via_drill": 0.3},
    "Diff100": {"track_width": 0.15, "clearance": 0.2, "diff_pair_width": 0.15, "diff_pair_gap": 0.2, "via_diameter": 0.6, "via_drill": 0.3},
    "HighVoltage": {"track_width": 0.5, "clearance": 2.5, "via_diameter": 1.0, "via_drill": 0.5},
    "Analog": {"track_width": 0.25, "clearance": 0.25, "via_diameter": 0.6, "via_drill": 0.3},
    "RF50": {"track_width": 0.35, "clearance": 0.3, "via_diameter": 0.6, "via_drill": 0.3},
}


def netclasses_from_plan(plan: DesignPlan, stackup_note: str = "") -> Dict[str, List[str]]:
    groups = defaultdict(list)
    for n in plan.nets:
        cls = classify_net(n.name, n.net_class)
        if n.current_a and n.current_a >= 3:
            groups["HighCurrent"].append(n.name)
        elif cls == "power":
            groups["Power"].append(n.name)
        elif cls == "ground":
            groups["Ground"].append(n.name)
        elif cls in ("diff_pair",):
            groups["Diff100" if (n.impedance_ohm or 100) >= 95 else "Diff90"].append(n.name)
        elif cls in ("high_speed",):
            groups["HighSpeed"].append(n.name)
        elif cls in ("high_voltage",):
            groups["HighVoltage"].append(n.name)
        elif cls in ("analog",):
            groups["Analog"].append(n.name)
        elif cls in ("rf",):
            groups["RF50"].append(n.name)
    return dict(groups)


def apply_netclasses(project_file: str, assignments: Dict[str, List[str]], overrides: Optional[Dict[str, dict]] = None) -> Dict:
    """Write net classes + name patterns (exact, plus */NAME for sheet-local nets) into a .kicad_pro (KiCad 7+ format). Backs up first."""
    with open(project_file, encoding="utf-8") as f:
        pro = json.load(f)
    backup(project_file)
    ns = pro.setdefault("net_settings", {})
    classes = ns.setdefault("classes", [])
    default = next((c for c in classes if c.get("name") == "Default"), None)
    by_name = {c.get("name"): c for c in classes}
    created = []
    for name in assignments:
        params = dict(NETCLASS_DEFAULTS.get(name, {}))
        params.update((overrides or {}).get(name, {}))
        if name in by_name:
            by_name[name].update(params)
        else:
            base = dict(default) if default else {}
            base.update({"name": name, **params})
            base.setdefault("priority", len(classes))
            classes.append(base)
            created.append(name)
    pats = ns.setdefault("netclass_patterns", [])
    existing = {(p.get("netclass"), p.get("pattern")) for p in pats}
    added = 0
    for cls, nets in assignments.items():
        for n in nets:
            # sheet-local nets are named /Sheet/NET on the board: add a wildcard for them too
            for pattern in ([n] if "/" in n else [n, "*/" + n]):
                key = (cls, pattern)
                if key not in existing:
                    pats.append({"netclass": cls, "pattern": pattern})
                    existing.add(key)
                    added += 1
    with open(project_file, "w", encoding="utf-8") as f:
        json.dump(pro, f, indent=2)
    return {"classes_created": created, "patterns_added": added, "file": project_file,
            "note": "Reopen the project (or Board Setup → Net Classes) to see the classes. Each net gets its exact name plus "
                    "a */NAME wildcard so sheet-local nets (/Sheet/NAME) are covered too."}


def write_custom_rules(project_dir: str, project_name: str, rules: List[str]) -> Dict:
    """Append custom DRC rules (.kicad_dru). Each rule is full (rule ...) text."""
    path = os.path.join(project_dir, project_name + ".kicad_dru")
    text = ""
    if os.path.exists(path):
        backup(path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
    if "(version" not in text:
        text = "(version 1)\n" + text
    for r in rules:
        parse(r)  # validate syntax
        text += "\n" + r.strip() + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return {"file": path, "rules_added": len(rules)}


RULE_TEMPLATES = {
    "hv_clearance": '(rule "HV clearance"\n  (constraint clearance (min {mm}mm))\n  (condition "A.NetClass == \'HighVoltage\' && B.NetClass != \'HighVoltage\'"))',
    "diff_pair_skew": '(rule "Diff pair skew {cls}"\n  (condition "A.NetClass == \'{cls}\'")\n  (constraint skew (max {mm}mm)))',
    "length_match_group": '(rule "Length {name}"\n  (condition "A.NetName == \'{pattern}\'")\n  (constraint length (min {min}mm) (max {max}mm)))',
    "courtyard_bga_decap": '(rule "BGA decap tighter spacing"\n  (layer outer)\n  (condition "A.Type == \'Footprint\' && B.Type == \'Footprint\'")\n  (constraint courtyard_clearance (min 0mm)))',
    "power_min_width": '(rule "Power min width"\n  (condition "A.NetClass == \'Power\'")\n  (constraint track_width (min {mm}mm)))',
}


def _tht_boxes(f, keepout: float = 0.5):
    out = []
    for pd in f.pads:
        if pd.kind in ("thru_hole", "np_thru_hole"):
            r = max(pd.w, pd.h, pd.drill) / 2 + keepout
            out.append((pd.x - r, pd.y - r, pd.x + r, pd.y + r))
    return out


_PASSIVE_RE = re.compile(r"^(C|R|L|FB|D|LED|F)\d")
_ANCHOR_RE = re.compile(r"^(U|IC|J|P|CN|X|Y|SW|Q|H|MH)\d")


def _passive_moves(board: Board, plan, fps, net_pads, ics) -> List[Dict]:
    """Target positions for small passives: each goes next to the IC/connector pin it serves.

    * decoupling caps (ground + supply) → the supply pins of the IC in the same plan block, one cap per pin first,
      smallest value closest;
    * other passives → the IC/connector pin on their signal net (pull-ups, filters, load caps, dividers);
    * passives that only touch other passives follow their partner.
    Every target is searched for a free spot inside the board outline that does not overlap any courtyard."""
    bx0, by0, bx1, by1 = board.board_bbox()
    margin = 0.4
    block = {}
    if plan is not None:
        block = {c.ref: c.block for c in plan.components}

    def on_board(f):
        cx, cy = (f.courtyard[0] + f.courtyard[2]) / 2, (f.courtyard[1] + f.courtyard[3]) / 2
        return bx0 <= cx <= bx1 and by0 <= cy <= by1

    def small(f):
        return len(f.pads) <= 3 and _PASSIVE_RE.match(f.ref) and \
            (f.courtyard[2] - f.courtyard[0]) * (f.courtyard[3] - f.courtyard[1]) < 14  # up to 1206 / 0805 / SOD-123

    movers = [f for f in board.footprints if small(f) and not f.locked]
    anchors = [f for f in board.footprints if f not in movers and on_board(f)]
    occupied = []
    for f in anchors:
        occupied.append((f.courtyard, f.layer[:1]))
        for box in _tht_boxes(f):  # drilled pads block the other side too
            occupied.append((box, "B" if f.layer.startswith("F") else "F"))
    # passives already sitting near their pin stay put
    def value_rank(f):
        v = (f.value or "").lower().replace("µ", "u")
        m = re.match(r"([\d.]+)\s*([pnum]?)", v)
        if not m:
            return 1e9
        try:
            return float(m.group(1)) * {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "": 1}[m.group(2)]
        except ValueError:
            return 1e9

    served = defaultdict(int)  # (ic ref, pad number) -> caps assigned

    def targets_for(c):
        nets = [p.net for p in c.pads if p.net]
        gnd = [n for n in nets if classify_net(n) == "ground"]
        other = [n for n in nets if n not in gnd]
        same_block = lambda r: block.get(r) and block.get(r) == block.get(c.ref)
        cands = []
        if re.match(r"^C\d", c.ref) and gnd and other:
            for ic in ics:
                if not on_board(ic):
                    continue
                for p in ic.pads:
                    supply = p.pintype.startswith("power_in") or (not p.pintype and classify_net(p.net) == "power")
                    if p.net in other and supply:
                        cands.append((0 if same_block(ic.ref) else 1, served[(ic.ref, p.number)], ic, p, "decoupling"))
            if not cands:  # bulk/filter caps on a rail: next to whatever uses the rail in the same block
                for n in other:
                    for r, p in net_pads.get(n, []):
                        f = fps.get(r)
                        if f in anchors and _ANCHOR_RE.match(r):
                            cands.append((0 if same_block(r) else 1, served[(r, p.number)], f, p,
                                          "bulk / filter cap" if classify_net(n) == "power" else "load / filter cap"))
        else:
            for n in other or nets:
                if classify_net(n) in ("ground",):
                    continue
                for r, p in net_pads.get(n, []):
                    f = fps.get(r)
                    if f is None or r == c.ref or f not in anchors or not _ANCHOR_RE.match(r):
                        continue
                    rail = classify_net(n) == "power"
                    cands.append((0 if same_block(r) else 1, 1 if rail else 0, f, p, "belongs next to"))
        if not cands:
            return None
        cands.sort(key=lambda t: (t[0], t[1], math.hypot(t[3].x - c.x, t[3].y - c.y)))
        return cands[0]

    def free(box, side):
        x0, y0, x1, y1 = box
        if x0 < bx0 + margin or y0 < by0 + margin or x1 > bx1 - margin or y1 > by1 - margin:
            return False
        for (a0, b0, a1, b1), sd in occupied:
            if sd == side and x0 < a1 + 0.15 and a0 < x1 + 0.15 and y0 < b1 + 0.15 and b0 < y1 + 0.15:
                return False
        return True

    def spot(tx, ty, w, h, side):
        best = None
        step = 0.25
        for ring in range(0, 60):
            r = ring * step
            pts = [(tx, ty)] if ring == 0 else \
                [(tx + r * math.cos(t * math.pi / (4 * ring)), ty + r * math.sin(t * math.pi / (4 * ring)))
                 for t in range(8 * ring)]
            for x, y in pts:
                x, y = round(x / 0.05) * 0.05, round(y / 0.05) * 0.05
                if free((x - w / 2, y - h / 2, x + w / 2, y + h / 2), side):
                    d = math.hypot(x - tx, y - ty)
                    if best is None or d < best[0]:
                        best = (d, x, y)
            if best:
                return best[1], best[2]
        return None

    moves = []
    order = sorted(movers, key=lambda f: (0 if re.match(r"^C\d", f.ref) else 1, value_rank(f), f.ref))
    pending = []
    placed_at = {}
    placed_side = {}
    for c in order:
        t = targets_for(c)
        if t is None:
            pending.append(c)
            continue
        _, _, ic, p, why = t
        if re.match(r"^C\d", c.ref):
            served[(ic.ref, p.number)] += 1
        vx, vy = p.x - ic.x, p.y - ic.y
        n = math.hypot(vx, vy) or 1
        vx, vy = vx / n, vy / n
        horizontal = abs(vx) > abs(vy)
        cw, ch = c.courtyard[2] - c.courtyard[0], c.courtyard[3] - c.courtyard[1]
        long_, short_ = max(cw, ch), min(cw, ch)
        rot = 0 if horizontal else 90
        w, h = (long_, short_) if rot == 0 else (short_, long_)
        tx, ty = p.x + vx * (long_ / 2 + 0.6), p.y + vy * (long_ / 2 + 0.6)
        side = "B" if ic.layer.startswith("B") else "F"
        other = "F" if side == "B" else "B"
        pos = spot(tx, ty, w, h, side)
        if pos is None or math.hypot(pos[0] - tx, pos[1] - ty) > 6:
            alt = spot(p.x, p.y, w, h, other)  # other side, under the pin
            if alt is not None and (pos is None or math.hypot(alt[0] - p.x, alt[1] - p.y) < math.hypot(pos[0] - tx, pos[1] - ty)):
                pos, side = alt, other
        if pos is None:
            continue
        # already in a good spot (e.g. second pass, or the user placed it): keep it
        if on_board(c) and ((free(c.courtyard, c.layer[:1]) and
                             math.hypot(p.x - c.x, p.y - c.y) <= math.hypot(p.x - pos[0], p.y - pos[1]) + 0.75)
                            or math.hypot(pos[0] - c.x, pos[1] - c.y) < 0.6):
            occupied.append((c.courtyard, c.layer[:1]))
            placed_at[c.ref] = (c.x, c.y)
            placed_side[c.ref] = c.layer[:1]
            continue
        x, y = pos
        occupied.append(((x - w / 2, y - h / 2, x + w / 2, y + h / 2), side))
        placed_at[c.ref] = (x, y)
        placed_side[c.ref] = side
        d = math.hypot(p.x - c.x, p.y - c.y)
        mv = {"ref": c.ref, "x_mm": round(x, 3), "y_mm": round(y, 3), "rotation": rot,
              "reason": f"{why} {'' if why == 'belongs next to' else 'for '}{ic.ref} pin {p.number} ({p.net}), currently {d:.1f} mm away"}
        mv["side"] = "bottom" if side == "B" else "top"
        if side != ("B" if ic.layer.startswith("B") else "F"):
            mv["reason"] += f" — no room on the {'top' if side == 'B' else 'bottom'} next to the pin, placed on the other side under it"
        moves.append(mv)
    # passives that only touch other passives (divider midpoints, series chains) go next to a placed partner
    for c in pending:
        partner = None
        for p in c.pads:
            for r, q in net_pads.get(p.net, []):
                if r != c.ref and r in placed_at and classify_net(p.net) != "ground":
                    partner = (r, q)
                    break
            if partner:
                break
        if not partner:
            continue
        cw, ch = c.courtyard[2] - c.courtyard[0], c.courtyard[3] - c.courtyard[1]
        pside = placed_side.get(partner[0], "F")
        px_, py_ = placed_at[partner[0]]  # where the partner is now (it may have just been moved)
        if on_board(c) and math.hypot(px_ - c.x, py_ - c.y) <= 4.0 and free(c.courtyard, c.layer[:1]):
            occupied.append((c.courtyard, c.layer[:1]))
            placed_at[c.ref] = (c.x, c.y)
            continue
        pos = spot(px_, py_, max(cw, ch), min(cw, ch), pside)
        if pos is None:
            continue
        x, y = pos
        w, h = max(cw, ch), min(cw, ch)
        occupied.append(((x - w / 2, y - h / 2, x + w / 2, y + h / 2), pside))
        placed_at[c.ref] = (x, y)
        moves.append({"ref": c.ref, "x_mm": round(x, 3), "y_mm": round(y, 3), "rotation": 0,
                      "side": "bottom" if pside == "B" else "top",
                      "reason": f"next to {partner[0]} (shares net {partner[1].net})"})
    return moves


# ---------------------------------------------------------------- placement
def placement_suggestions(board: Board, plan: Optional[DesignPlan] = None) -> Dict:
    """Group-aware placement advice with concrete target coordinates for decoupling capacitors and small passives."""
    fps = {f.ref: f for f in board.footprints}
    net_pads = board.net_pads()
    ics = [f for f in board.footprints if re.match(r"^(U|IC|Q|VR|PS)\d", f.ref) and len(f.pads) >= 3]
    suggestions = []
    moves = _passive_moves(board, plan, fps, net_pads, ics)
    # 2. groups by schematic sheet
    by_sheet = defaultdict(list)
    for f in board.footprints:
        by_sheet[f.sheet or "/"].append(f.ref)
    if len(by_sheet) > 1:
        suggestions.append({"rule": "group by function",
                            "detail": "Place each schematic sheet's parts together (in KiCad: select a sheet's parts with "
                                      "cross-probing, then press P → 'Pack and move footprints'). Groups: "
                                      + "; ".join(f"{k}: {len(v)} parts" for k, v in by_sheet.items())})
    # 3. connectors to edges
    bx0, by0, bx1, by1 = board.board_bbox()
    for f in board.footprints:
        if re.match(r"^(J|P|CN|X)\d", f.ref):
            dist = min(f.x - bx0, bx1 - f.x, f.y - by0, by1 - f.y)
            if dist > 8:
                suggestions.append({"rule": "connectors at the edge", "ref": f.ref,
                                    "detail": f"{f.ref} is {dist:.0f} mm from the nearest board edge; cables and mating "
                                              "parts need it at the edge (and it keeps cable-borne noise out of the middle of the board)."})
    # 4. crystals near their IC
    for f in board.footprints:
        if re.match(r"^(Y|X)\d", f.ref) and len(f.pads) >= 2:
            partner = None
            for p in f.pads:
                if not p.net or classify_net(p.net) in ("ground", "power"):
                    continue
                for r, q in net_pads.get(p.net, []):
                    if r != f.ref and r in fps and re.match(r"^(U|IC)\d", r):
                        partner = (r, q)
            if partner:
                d = math.hypot(partner[1].x - f.x, partner[1].y - f.y)
                if d > 6:
                    suggestions.append({"rule": "crystal close to IC", "ref": f.ref,
                                        "detail": f"{f.ref} is {d:.1f} mm from {partner[0]}; keep crystal + load caps within ~5 mm, "
                                                  "same layer, ground pour beneath, no other signals under it."})
    # 5. overlap check
    overlaps = []
    items = [(f.ref, f.courtyard, f.layer[:1]) for f in board.footprints]
    items += [(f.ref + " (through-hole pad)", box, "B" if f.layer.startswith("F") else "F")
              for f in board.footprints for box in _tht_boxes(f)]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a[2] != b[2] or a[0].split(" ")[0] == b[0].split(" ")[0]:
                continue
            (ax0, ay0, ax1, ay1), (bx0_, by0_, bx1_, by1_) = a[1], b[1]
            if ax0 < bx1_ and bx0_ < ax1 and ay0 < by1_ and by0_ < ay1:
                msg = f"{a[0]} ↔ {b[0]}"
                if msg not in overlaps:
                    overlaps.append(msg)
                if len(overlaps) > 60:
                    break
    return {"moves": moves, "suggestions": suggestions, "courtyard_overlaps": overlaps[:60],
            "how_to_apply": "Say 'apply the moves' — with KiCad's API enabled I move them live (one undo step); otherwise I "
                            "edit the .kicad_pcb file while the PCB editor is closed (a backup is kept)."}


# ---------------------------------------------------------------- flip (file mode)
def _swap_side(layer: str) -> str:
    if layer.startswith("F."):
        return "B." + layer[2:]
    if layer.startswith("B."):
        return "F." + layer[2:]
    return layer


def _num(v) -> float:
    return float(v)


def _mirror_xy_node(n: Node):
    """(at|start|end|mid|center|xy x y ...) → negate y."""
    if len(n.items) >= 3:
        n.items[2] = fmt_num(-_num(n.items[2]))


def flip_footprint_node(fp: Node):
    """Flip a footprint to the other side exactly as KiCad's top/bottom flip does: mirror every child's local Y,
    negate the footprint and pad angles, text angle → 180 − a, swap F./B. layers, toggle text mirroring.
    Validated against pcbnew's FOOTPRINT::Flip (tests/test_flip.py)."""
    at = fp.child("at")
    fp_rot = _num(at.items[3]) if len(at.items) > 3 else 0.0
    new_rot = ((-fp_rot + 180) % 360) - 180
    at.items[3:] = [fmt_num(new_rot)] if new_rot else []

    def norm(a):
        a = ((a + 180) % 360) - 180
        return 180.0 if a == -180 else a

    def walk(n: Node, in_pad: bool = False, in_primitives: bool = False):
        for ch in n.items[1:]:
            if not isinstance(ch, Node):
                continue
            h = ch.head
            if h in ("layer",):
                ch.items[1] = QStr(_swap_side(str(ch.items[1])))
            elif h == "layers":
                ch.items[1:] = [QStr(_swap_side(str(v))) for v in ch.items[1:]]
            elif h == "at" and n.head in ("pad", "fp_text", "property", "fp_text_box"):
                nums = [v for v in ch.items[1:] if not isinstance(v, Node) and str(v) != "unlocked"]
                extra = [v for v in ch.items[1:] if str(v) == "unlocked"]
                x, y = _num(nums[0]), -_num(nums[1])
                a = _num(nums[2]) if len(nums) > 2 else 0.0
                if n.head == "pad":
                    a = norm(-a)
                else:
                    a = norm(180 - a)
                ch.items[1:] = [fmt_num(x), fmt_num(y)] + ([fmt_num(a)] if a else []) + extra
            elif h in ("start", "end", "mid", "center", "xy") and not (in_pad and not in_primitives):
                _mirror_xy_node(ch)
            elif h == "rect_delta":
                pass
            elif h == "effects":
                j = ch.child("justify")
                if j is None:
                    ch.items.append(Node(["justify", "mirror"]))
                elif "mirror" in [str(v) for v in j.items[1:]]:
                    j.items[1:] = [v for v in j.items[1:] if str(v) != "mirror"]
                    if len(j.items) == 1:
                        ch.items.remove(j)
                else:
                    j.items.append("mirror")
            elif h == "model":
                continue
            elif h in ("offset",) and in_pad:
                _mirror_xy_node(ch)
                continue
            if h in ("pad",):
                walk(ch, True, False)
            elif h == "primitives":
                walk(ch, in_pad, True)
            elif h not in ("at", "layer", "layers", "start", "end", "mid", "center", "xy", "effects", "model"):
                walk(ch, in_pad, in_primitives)

    walk(fp)
    return fp



def move_footprints_in_file(pcb_path: str, moves: List[Dict]) -> Dict:
    """Edit footprint positions/rotations in the .kicad_pcb text. Pad and text angles are rotated consistently."""
    lock = lock_file_for(pcb_path)
    if lock:
        return {"error": "The board is open in KiCad (lock file present). Enable the KiCad API for live moves, or close "
                         "the PCB editor first so the file edit is not overwritten."}
    with open(pcb_path, encoding="utf-8") as f:
        text = f.read()
    root = parse(text)
    fps = {}
    for n in root.children("footprint"):
        ref = None
        for p in n.children("property"):
            if str(p.items[1]) == "Reference":
                ref = str(p.items[2])
        for t in n.children("fp_text"):
            if str(t.items[1]) == "reference":
                ref = ref or str(t.items[2])
        if ref:
            fps[ref] = n
    edits: List[Tuple[int, int, str]] = []
    done, missing, locked, side_unsupported, flipped = [], [], [], [], []
    for m in moves:
        n = fps.get(m["ref"])
        if n is None:
            missing.append(m["ref"])
            continue
        if "locked" in n.atoms() or (n.child("locked") is not None and n.value("locked") != "no"):
            locked.append(m["ref"])
            continue
        if m.get("side"):
            cur_side = "bottom" if str(n.value("layer", "F.Cu")).startswith("B.") else "top"
            if m["side"] != cur_side:
                flip_footprint_node(n)
                at = n.child("at")
                cur = _num(at.items[3]) if len(at.items) > 3 else 0.0
                new_rot = float(m["rotation"]) if m.get("rotation") is not None else cur
                delta = new_rot - cur
                at.items[1:] = [fmt_num(float(m["x_mm"])), fmt_num(float(m["y_mm"]))] + ([fmt_num(new_rot)] if new_rot else [])
                if delta:
                    for child in n.items:
                        if isinstance(child, Node) and child.head in ("pad", "property", "fp_text"):
                            cat = child.child("at")
                            if cat is None:
                                continue
                            nums = [a for a in cat.items[1:] if not isinstance(a, Node) and str(a) != "unlocked"]
                            extra = [a for a in cat.items[1:] if str(a) == "unlocked"]
                            ang = ((_num(nums[2]) if len(nums) > 2 else 0.0) + delta + 180) % 360 - 180
                            cat.items[1:] = [nums[0], nums[1]] + ([fmt_num(ang)] if ang else []) + extra
                edits.append((n.start, n.end, dump(n, 1).lstrip()))
                flipped.append(m["ref"])
                done.append(m["ref"])
                continue
        at = n.child("at")
        old = at.items[1:]
        old_rot = float(old[2]) if len(old) > 2 else 0.0
        new_rot = float(m["rotation"]) if m.get("rotation") is not None else old_rot
        delta = new_rot - old_rot
        edits.append((at.start, at.end, f"(at {fmt_num(float(m['x_mm']))} {fmt_num(float(m['y_mm']))}"
                                        + (f" {fmt_num(new_rot)}" if new_rot else "") + ")"))
        if delta:
            for child in n.items:
                if isinstance(child, Node) and child.head in ("pad", "property", "fp_text"):
                    cat = child.child("at")
                    if cat is None:
                        continue
                    nums = [a for a in cat.items[1:] if not isinstance(a, Node)]
                    extra = [a for a in nums if a == "unlocked"]
                    vals = [float(a) for a in nums if a != "unlocked"]
                    ang = (vals[2] if len(vals) > 2 else 0.0) + delta
                    ang = ((ang + 180) % 360) - 180
                    s = f"(at {fmt_num(vals[0])} {fmt_num(vals[1])}" + (f" {fmt_num(ang)}" if ang else "") + \
                        ("".join(" " + e for e in extra)) + ")"
                    edits.append((cat.start, cat.end, s))
        done.append(m["ref"])
    notes = {}
    if locked:
        notes["locked_skipped"] = locked
    if flipped:
        notes["flipped"] = flipped
    if not edits:
        return {"moved": [], "missing": missing, **notes}
    bk = backup(pcb_path)
    for s, e, rep in sorted(edits, key=lambda t: -t[0]):
        text = text[:s] + rep + text[e:]
    parse(text)
    with open(pcb_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return {"moved": done, "missing": missing, "backup": bk, **notes}
