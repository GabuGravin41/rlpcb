"""Teaching: what a component or a net does in this circuit, and why it is there.

Works from the design plan (and the schematic when the plan has no entry), reading the part's connections the way an
engineer reads a schematic: a capacitor from a rail to ground is decoupling or bulk storage, a resistor from a signal
to a rail is a pull-up, two resistors from a rail to ground with a tap are a divider, and so on. Each explanation says
what the part does, what goes wrong without it, and what to check — so a beginner learns the pattern, not just the
answer. Inferred roles are marked as inferred.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .verify import classify_net


def _val(v: str) -> Optional[float]:
    m = re.match(r"\s*([0-9.]+)\s*([pnuµmkMR]?)", v or "")
    if not m:
        return None
    x = float(m.group(1))
    return x * {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6, "R": 1, "": 1}[m.group(2)]


def _kind(net: str, declared: str = "") -> str:
    if re.search(r"(^|[_/])(SW|LX)$", net.split("/")[-1], re.I):
        return "switching"
    return classify_net(net, declared if declared in ("power", "ground") else "")


def infer_role(ref: str, value: str, pin_nets: Dict[str, str], others: Dict[str, List[str]]) -> Dict:
    """pin_nets: pin → net; others: net → other refs on it. Returns {role, explanation, without_it, check}."""
    nets = [n for n in pin_nets.values() if n]
    kinds = [_kind(n) for n in nets]
    pfx = re.match(r"[A-Z]+", ref).group(0) if re.match(r"[A-Z]+", ref) else ""
    v = _val(value)
    ics = sorted({r for n, k in zip(nets, kinds) if k not in ("ground",) for r in others.get(n, [])
                  if re.match(r"^(U|IC)\d", r)})
    if pfx in ("Y", "X", "C"):
        sig_ics = sorted({r for n, k in zip(nets, kinds) if k == "signal" for r in others.get(n, [])
                          if re.match(r"^(U|IC)\d", r)})
        ics = sig_ics or ics
    if re.search(r"USBLC|ESD|TVS|SMAJ|SMBJ|PESD|TPD\d|PRTR|SP05", value or "", re.I):
        return {"role": "ESD / surge protection", "explanation": "clamps electrostatic discharges and surges on the "
                "lines it sits on before they reach the chips behind it", "without_it": "a touch or a cable plug can "
                "destroy the interface chip", "check": "at the connector, with a short, wide path to ground; standoff "
                                                       "voltage above the line's normal level"}
    near = f" for {', '.join(ics[:3])}" if ics else ""
    if pfx == "C" and "ground" in kinds and ("power" in kinds or "switching" in kinds):
        rail = next(n for n, k in zip(nets, kinds) if k != "ground")
        if v is not None and v <= 1.1e-6:
            return {"role": "decoupling capacitor", "explanation": f"supplies the fast current spikes on {rail}{near} "
                    "locally, so they do not travel through the board's supply wiring",
                    "without_it": "supply noise, resets, radio and ADC errors, emissions",
                    "check": "place it within ~2–3 mm of the pin it serves, with its ground via right at the pad"}
        return {"role": "bulk capacitor", "explanation": f"stores charge on {rail} to cover load steps and keep the "
                "regulator stable", "without_it": "voltage dips on load steps, regulator instability or oscillation",
                "check": "voltage rating ≥ 1.5–2× the rail (ceramics lose capacitance under DC bias); ESR within the "
                         "regulator's stability range"}
    if pfx == "C" and len(nets) == 2 and "ground" in kinds:
        sig = next(n for n, k in zip(nets, kinds) if k != "ground")
        if re.search(r"OSC|XTAL|XI|XO", sig, re.I):
            return {"role": "crystal load capacitor", "explanation": f"sets the load capacitance of the crystal on {sig} "
                    "so it oscillates at its specified frequency", "without_it": "the clock runs off-frequency or does "
                    "not start", "check": "C = 2 × (CL − Cstray); RL PCB's calculate has crystal_caps"}
        return {"role": "filter capacitor", "explanation": f"filters noise on {sig} (with the resistance feeding it, an RC "
                "low-pass)", "without_it": "noisy readings or false triggering", "check": "the RC corner frequency vs "
                                                                                       "the signal's bandwidth"}
    if pfx == "R" and len(nets) == 2:
        if "power" in kinds and "ground" not in kinds and kinds.count("power") == 1:
            sig = next(n for n, k in zip(nets, kinds) if k != "power")
            rail = next(n for n, k in zip(nets, kinds) if k == "power")
            tied = [r for r in others.get(sig, []) if re.match(r"^R\d", r) and r != ref]
            if tied:
                return {"role": "voltage divider (upper resistor)", "explanation": f"with {', '.join(tied)}, scales "
                        f"{rail} down to {sig} for an ADC or a regulator's feedback pin", "without_it": "the measured "
                        "or regulated voltage is wrong", "check": "ratio, tolerance (1 % for feedback), and that the "
                                                                  "divider current is small but well above the pin's leakage"}
            return {"role": "pull-up resistor", "explanation": f"holds {sig} high (at {rail}) when nothing drives it low",
                    "without_it": "the line floats: random levels, a bus that never works (I²C), a chip that does not "
                                  "leave reset", "check": "value vs speed: I²C 2.2–4.7 kΩ, reset/enable 10 kΩ"}
        if "ground" in kinds and "power" not in kinds:
            sig = next(n for n, k in zip(nets, kinds) if k != "ground")
            if re.search(r"CC\d", sig, re.I):
                return {"role": "USB-C CC pull-down (5.1 kΩ)", "explanation": "tells the USB-C source this is a device "
                        "that wants 5 V", "without_it": "many chargers and cables give no power at all",
                        "check": "one 5.1 kΩ per CC pin, never shared"}
            tied = [r for r in others.get(sig, []) if re.match(r"^R\d", r) and r != ref]
            if tied:
                return {"role": "voltage divider (lower resistor)", "explanation": f"with {', '.join(tied)}, sets the "
                        f"voltage on {sig}", "without_it": "", "check": "ratio and tolerance"}
            return {"role": "pull-down resistor", "explanation": f"holds {sig} low when nothing drives it (e.g. a BOOT "
                    "pin at reset)", "without_it": "undefined level at power-up", "check": "value vs the pin's "
                                                                                           "required level"}
        if "power" not in kinds and "ground" not in kinds:
            if any(re.search(r"LED", n, re.I) for n in nets) or (v and 100 <= v <= 10e3 and any(
                    re.match(r"^D\d", r) for n in nets for r in others.get(n, []))):
                return {"role": "LED current-limiting resistor", "explanation": "sets the LED current to (V − Vf)/R",
                        "without_it": "the LED or the pin driving it burns", "check": "1–5 mA is plenty for an "
                                                                                     "indicator; RL PCB's led_indicator block "
                                                                                     "calculates it"}
            return {"role": "series resistor", "explanation": f"in series between {nets[0]} and {nets[1]}: limits current, "
                    "damps ringing on a fast line, or isolates two circuits", "without_it": "overshoot and ringing on "
                    "fast edges, or excess current between two drivers", "check": "22–33 Ω at the driver for "
                                                                                  "damping; larger for protection"}
    if pfx in ("L", "FB"):
        if "switching" in kinds:
            return {"role": "buck/boost inductor", "explanation": "stores energy each switching cycle; with the output "
                    "capacitor it smooths the switch node's pulses into DC", "without_it": "no conversion",
                    "check": "saturation current ≥ 1.3× peak current, DCR for efficiency, placed tight against the SW pin"}
        return {"role": "ferrite / filter inductor", "explanation": f"blocks high-frequency noise between {nets[0]} and "
                f"{nets[-1]} while passing DC", "without_it": "noise from one rail reaches a sensitive one (analog, "
                "sensor, radio)", "check": "current rating and DC resistance at the load current"}
    if pfx == "D":
        if re.search(r"SMAJ|SMBJ|TVS|ESD|PESD", value or "", re.I):
            return {"role": "TVS clamp", "explanation": "clamps voltage spikes (ESD, surges, inductive kicks) to a safe "
                    "level", "without_it": "a spike destroys the parts behind it", "check": "standoff voltage above the "
                                                                                           "normal maximum; at the connector"}
        if re.search(r"LED|red|green|blue|yellow|white", value or "", re.I):
            return {"role": "indicator LED", "explanation": "shows a state", "without_it": "", "check": "series "
                    "resistor; polarity (anode to the positive side)"}
        if "switching" in kinds:
            return {"role": "catch (freewheel) diode", "explanation": "carries the inductor current while the buck's "
                    "switch is off", "without_it": "the switch node flies negative and destroys the regulator",
                    "check": "Schottky, current ≥ load, voltage ≥ input; in the hot loop, tight"}
        return {"role": "diode (OR-ing / reverse protection)", "explanation": f"lets current flow from {nets[0]} to "
                f"{nets[-1]} only", "without_it": "back-feeding between supplies or damage on reverse polarity",
                "check": "forward drop at full current; reverse voltage"}
    if pfx in ("Y", "X"):
        return {"role": "crystal", "explanation": f"clock reference{near}", "without_it": "the MCU runs on its "
                "internal RC oscillator (inaccurate: no USB, no precise UART)", "check": "within ~5 mm of the MCU, "
                                                                                       "load caps sized for its CL"}
    if pfx in ("J", "P"):
        return {"role": "connector", "explanation": "the interface to cables or other boards", "without_it": "",
                "check": "pinout matches the mating part (RL PCB system_check), ESD protection on lines that leave the "
                         "board, mechanical position (mech_export / RL CAD)"}
    if pfx in ("U", "IC"):
        return {"role": "integrated circuit", "explanation": f"{value}: see its datasheet's typical application; "
                "the parts around it are mostly its decoupling, configuration and support", "without_it": "",
                "check": "every power pin decoupled, every ground pin grounded, configuration pins defined at reset"}
    if pfx in ("SW", "S"):
        return {"role": "switch / button", "explanation": "user input", "without_it": "", "check": "a pull-up or "
                "pull-down and debouncing (RC or firmware)"}
    return {"role": "part", "explanation": "", "without_it": "", "check": ""}


def explain_component(plan, ref: str, sch_pins: Optional[List[Dict]] = None, pin_lookup=None) -> Dict:
    """Explanation of one part from the plan (or schematic pins if the plan lacks it)."""
    c = plan.comp(ref) if plan else None
    pin_nets: Dict[str, str] = {}
    others: Dict[str, List[str]] = {}
    if plan:
        for n in plan.nets:
            refs = [x.split(".")[0] for x in n.nodes]
            others[n.name] = refs
            for x in n.nodes:
                r, _, pin = x.partition(".")
                if r == ref:
                    pin_nets[pin] = n.name
    if not pin_nets and sch_pins:
        for row in sch_pins:
            pin_nets[str(row.get("pin"))] = row.get("net") or ""
    names = {}
    if c and pin_lookup:
        names = {str(p.get("number")): p.get("name") for p in pin_lookup(c.lib_id) or []}
    value = c.value if c else ""
    role = infer_role(ref, value, pin_nets, {k: [r for r in v if r != ref] for k, v in others.items()})
    out = {"ref": ref, "value": value, "lib_id": c.lib_id if c else "", "footprint": c.footprint if c else "",
           "block": c.block if c else "", "role_in_plan": c.role if c else "",
           "inferred_role": role["role"], "what_it_does": role["explanation"], "without_it": role["without_it"],
           "check": role["check"],
           "connections": [{"pin": p, "name": names.get(p, ""), "net": n,
                            "with": [r for r in others.get(n, []) if r != ref][:8]} for p, n in sorted(pin_nets.items())],
           "basis": "role from the plan entry" if (c and c.role) else "role inferred from the connections; confirm "
                                                                       "against the datasheet",
           "datasheet": (c.fields.get("Datasheet") or c.fields.get("datasheet")) if c else None}
    blk = next((b for b in plan.blocks if b.id == (c.block if c else "")), None) if plan else None
    if blk:
        out["block_purpose"] = blk.purpose
        out["block_notes"] = blk.notes
    return out


NET_ADVICE = {
    "ground": "the return path for every signal: keep it a solid plane, connect each ground pin with its own via, and "
              "never route a fast signal over a gap in it",
    "power": "size the copper for the current (calculate trace_width), decouple at every load, and keep the regulator's "
             "output loop short",
    "switching": "the switch node of a converter: as small and short as possible, it radiates; nothing sensitive nearby",
    "high_speed": "a fast edge: route over an unbroken ground plane, short, few vias; pairs routed together and matched",
    "signal": "a logic signal: short and direct; pull-ups/downs where the level must be defined at reset",
}


def explain_net(plan, name: str) -> Dict:
    from ..pcb.review import net_kind
    n = plan.net(name) if plan else None
    if not n:
        cands = [x.name for x in plan.nets if re.search(name, x.name, re.I)] if plan else []
        raise ValueError(f"no net {name}; similar: {cands[:10]}")
    k = net_kind(n.name, n.net_class)
    members = [x for x in n.nodes]
    return {"net": n.name, "kind": k, "declared_class": n.net_class, "current_a": n.current_a, "voltage_v": n.voltage_v,
            "notes": n.notes, "members": members, "layout_advice": NET_ADVICE.get(k, NET_ADVICE["signal"]),
            "parts": sorted({x.split(".")[0] for x in members})}
