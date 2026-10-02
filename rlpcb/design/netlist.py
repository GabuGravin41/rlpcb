"""Export a design plan as a KiCad (s-expression) netlist, importable by the PCB editor."""
from __future__ import annotations

import os
import uuid
from typing import Callable, List

from ..kicad.sexpr import QStr, dump
from .plan import DesignPlan


def plan_to_kicad_netlist(plan: DesignPlan, path: str, pin_lookup: Callable[[str], List[dict]]) -> str:
    comps = []
    for c in plan.components:
        lib, _, part = c.lib_id.partition(":")
        comps.append(["comp", ["ref", QStr(c.ref)], ["value", QStr(c.value)], ["footprint", QStr(c.footprint)],
                      ["libsource", ["lib", QStr(lib)], ["part", QStr(part)], ["description", QStr(c.role)]],
                      ["sheetpath", ["names", QStr("/")], ["tstamps", QStr("/")]],
                      ["tstamps", QStr(str(uuid.uuid5(uuid.NAMESPACE_URL, plan.name + c.ref)))]])
    nets = []
    code = 1
    for n in plan.nets:
        nodes = []
        for node in n.nodes:
            ref, _, pin = node.partition(".")
            comp = plan.comp(ref)
            pinfo = next((p for p in (pin_lookup(comp.lib_id) if comp else []) if p["number"] == pin), None)
            item = ["node", ["ref", QStr(ref)], ["pin", QStr(pin)]]
            if pinfo:
                item += [["pinfunction", QStr(pinfo["name"])], ["pintype", QStr(pinfo["type"])]]
            nodes.append(item)
        nets.append(["net", ["code", QStr(str(code))], ["name", QStr(n.name)], *nodes])
        code += 1
    tree = ["export", ["version", QStr("E")], ["design", ["source", QStr(plan.name)], ["tool", QStr("RL PCB")]],
            ["components", *comps], ["nets", *nets]]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(dump(tree) + "\n")
    return path
