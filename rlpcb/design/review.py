"""Design-plan review (an ERC for intent, before anything is drawn) and plan import from an existing schematic."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Callable, Dict, List, Optional

from ..kicad.connectivity import Connectivity
from ..kicad.schematic import Hierarchy
from .plan import DesignPlan, PlanBlock, PlanComponent, PlanNet
from .verify import classify_net

DRIVER_TYPES = {"output", "power_out", "bidirectional", "tri_state", "passive", "open_collector", "open_emitter"}


def _nat(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def review_plan(plan: DesignPlan, pin_lookup: Callable[[str], List[dict]],
                fp_lookup: Optional[Callable[[str], Optional[dict]]] = None) -> Dict:
    errors, warnings, info = [], [], []
    owner = plan.node_net()
    nc = set(plan.no_connect)
    comp_pins: Dict[str, List[dict]] = {}
    for c in plan.components:
        pins = pin_lookup(c.lib_id) or []
        comp_pins[c.ref] = pins
        if not pins:
            warnings.append(f"{c.ref}: symbol {c.lib_id} not found in the library index — can't check its pins")
            continue
        # footprint checks
        if not c.footprint:
            warnings.append(f"{c.ref} ({c.value or c.lib_id}): no footprint chosen yet")
        elif fp_lookup:
            fp = fp_lookup(c.footprint)
            if fp is None:
                errors.append(f"{c.ref}: footprint {c.footprint} does not exist in the indexed libraries")
            else:
                sym_pins = {p["number"] for p in pins}
                n_sym = len(sym_pins)
                if fp["pad_count"] and n_sym and fp["pad_count"] not in (n_sym, n_sym + 1) and n_sym > 2:
                    warnings.append(f"{c.ref}: symbol has {n_sym} pins but footprint {c.footprint} has {fp['pad_count']} pads "
                                    "— check the pin↔pad mapping")
        # pin coverage
        unassigned = []
        for p in pins:
            node = f"{c.ref}.{p['number']}"
            if node in owner or node in nc or p["type"] == "no_connect":
                continue
            unassigned.append(p)
        if unassigned:
            power_un = [p for p in unassigned if p["type"] in ("power_in",)]
            input_un = [p for p in unassigned if p["type"] == "input"]
            if power_un:
                errors.append(f"{c.ref}: power pins not connected in the plan: "
                              + ", ".join(f"{p['number']} ({p['name']})" for p in power_un[:20]))
            if input_un:
                warnings.append(f"{c.ref}: input pins left floating (tie high/low or mark no-connect deliberately): "
                                + ", ".join(f"{p['number']} ({p['name']})" for p in input_un[:20]))
            rest = [p for p in unassigned if p not in power_un and p not in input_un]
            if rest:
                info.append(f"{c.ref}: {len(rest)} pins not yet assigned: "
                            + ", ".join(f"{p['number']} ({p['name']})" for p in rest[:25]) + (" …" if len(rest) > 25 else ""))
    # net-level checks
    pin_type = {}
    for ref, pins in comp_pins.items():
        for p in pins:
            pin_type[f"{ref}.{p['number']}"] = (p["type"], p["name"])
    for n in plan.nets:
        if len(n.nodes) == 1:
            warnings.append(f"Net {n.name} has only one pin ({n.nodes[0]})")
        types = [pin_type.get(x, ("?", ""))[0] for x in n.nodes]
        cls = classify_net(n.name, n.net_class)
        if types and all(t == "input" for t in types):
            warnings.append(f"Net {n.name}: only inputs ({', '.join(n.nodes)}) — nothing drives it")
        outs = [x for x, t in zip(n.nodes, types) if t in ("output", "power_out")]
        if len(outs) > 1 and cls not in ("power", "ground"):
            errors.append(f"Net {n.name}: several push-pull outputs tied together ({', '.join(outs)})")
        if len([t for t in types if t == "power_out"]) > 1:
            warnings.append(f"Net {n.name}: more than one power output ({', '.join(outs)}) — only OK with load-sharing/ORing")
        for x in n.nodes:
            if x in nc:
                errors.append(f"{x} is both on net {n.name} and marked no-connect")
    # decoupling heuristic: each IC power pin net should have at least one capacitor to ground
    caps_on = defaultdict(list)
    for n in plan.nets:
        for x in n.nodes:
            if re.match(r"^C\d", x.split(".")[0]):
                caps_on[n.name].append(x.split(".")[0])
    for c in plan.components:
        if not re.match(r"^(U|IC)\d", c.ref):
            continue
        pw_nets = set()
        for p in comp_pins.get(c.ref, []):
            if p["type"] == "power_in":
                net = owner.get(f"{c.ref}.{p['number']}")
                if net and classify_net(net) != "ground":
                    pw_nets.add(net)
        for net in pw_nets:
            if not caps_on.get(net):
                warnings.append(f"{c.ref}: supply net {net} has no capacitor in the plan — add local decoupling "
                                "(typ. 100 nF per power pin + bulk 1–10 µF per rail, check the datasheet)")
    # duplicate refs
    dup = [r for r, k in Counter(c.ref for c in plan.components).items() if k > 1]
    if dup:
        errors.append(f"Duplicate references: {', '.join(dup)}")
    ready = not errors
    return {"ready_to_draw": ready, "errors": errors, "warnings": warnings, "info": info,
            "summary": f"{len(plan.components)} parts, {len(plan.nets)} nets, {len(errors)} errors, {len(warnings)} warnings"}


def plan_from_schematic(hier: Hierarchy, name: Optional[str] = None) -> DesignPlan:
    """Capture an existing (drawn) schematic as a plan, so the copilot can reason about and extend it."""
    conn = Connectivity(hier)
    plan = DesignPlan(name=name or hier.project_name, description="Imported from existing schematic")
    comps = hier.components()
    sheets = sorted({c["sheet"] for c in comps.values()})
    for sh in sheets:
        plan.blocks.append(PlanBlock(id=sh.strip("/") or "root", title=sh))
    for ref, c in sorted(comps.items(), key=lambda kv: _nat(kv[0])):
        plan.components.append(PlanComponent(ref=ref, lib_id=c["lib_id"], value=c["value"], footprint=c["footprint"],
                                             block=c["sheet"].strip("/") or "root", fields=c.get("fields", {}),
                                             unit_count=len(set(c["units"])), dnp=c.get("dnp", False)))
    for nname, pins in conn.netlist().items():
        if len(pins) < 2:
            continue
        clean = nname.split("/")[-1] if nname.startswith("/") and nname.count("/") == 1 else nname
        plan.nets.append(PlanNet(name=clean, nodes=pins))
    nc = getattr(conn, "_nc_pins", set())
    plan.no_connect = sorted(f"{r}.{p}" for r, p in nc)
    return plan
