"""Automatic engineering checks: the things an experienced reviewer notices, turned into pass/fail findings.

Plan-level (no drawing needed):
  * capacitor voltage rating vs the rail it sits on;
  * inductor / connector current vs the net's planned current;
  * I2C lines and open-drain outputs without a pull-up;
  * rails fed by more than one source (back-feed risk);
  * parts that won't fit the board area.
Board-level (after F8 / placement):
  * decoupling capacitors far from the supply pin they serve;
  * crystal far from its IC;
  * tracks narrower than the IPC-2221 width for the net's current.

Every finding is {severity, rule, message, refs}; severity error | warning | info.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Callable, Dict, List, Optional

from ..calc import formulas as F
from .verify import classify_net

_SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6}


def parse_voltage(text: str) -> Optional[float]:
    """'10u 50V' → 50; '6V3' → 6.3; '+3V3' → 3.3; '+5V' → 5; '12V_AUX' → 12."""
    if not text:
        return None
    t = str(text)
    m = re.search(r"(\d+)[Vv](\d+)", t)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.search(r"(\d+(?:\.\d+)?)\s*[Vv](?![a-zA-Z])", t)
    if m:
        return float(m.group(1))
    return None


def parse_current(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(m?)A\b", str(text))
    if not m:
        return None
    return float(m.group(1)) * (1e-3 if m.group(2) else 1)


def net_voltage(net) -> Optional[float]:
    if net is None:
        return None
    if net.voltage_v:
        return float(net.voltage_v)
    if classify_net(net.name) == "ground":
        return 0.0
    return parse_voltage(net.name)


def _f(sev, rule, msg, refs=()):
    return {"severity": sev, "rule": rule, "message": msg, "refs": list(refs)}


def plan_checks(plan, pin_lookup: Callable[[str], List[dict]], fp_lookup: Optional[Callable] = None,
                board_area_mm2: Optional[float] = None, sides: int = 2) -> List[Dict]:
    out: List[Dict] = []
    nets = {n.name: n for n in plan.nets}
    owner = plan.node_net()
    comps = {c.ref: c for c in plan.components}
    pins_by_ref = {c.ref: {p["number"]: p for p in (pin_lookup(c.lib_id) or [])} for c in plan.components}

    def nets_of(ref):
        return {owner[k] for k in owner if k.split(".", 1)[0] == ref}

    # 1. capacitor voltage rating
    for c in plan.components:
        if not re.match(r"^C\d", c.ref):
            continue
        rating = parse_voltage(c.fields.get("Voltage", "")) or parse_voltage(c.value)
        vs = [v for v in (net_voltage(nets.get(n)) for n in nets_of(c.ref)) if v is not None]
        if not vs:
            continue
        vmax = max(vs) - min(vs) if len(vs) > 1 else max(vs)
        if vmax <= 0:
            continue
        if rating is None:
            if vmax > 16:
                out.append(_f("warning", "cap_voltage", f"{c.ref} ({c.value}) sits on {vmax:g} V but has no voltage rating "
                                                         "— add one (≥ 1.5× for ceramics)", [c.ref]))
            continue
        if rating < vmax:
            out.append(_f("error", "cap_voltage", f"{c.ref} is rated {rating:g} V but sees {vmax:g} V", [c.ref]))
        elif rating < 1.5 * vmax and vmax > 5:
            out.append(_f("warning", "cap_voltage", f"{c.ref} rated {rating:g} V on {vmax:g} V: ceramics lose most of "
                                                     "their capacitance near rated voltage — use ≥ 1.5×", [c.ref]))

    # 2. current ratings (inductors with Isat/Current fields, connectors with Current field)
    for c in plan.components:
        if not re.match(r"^(L|J|F)\d", c.ref):
            continue
        cap = parse_current(c.fields.get("Isat_min") or c.fields.get("Current") or c.fields.get("Isat") or "")
        need = max([nets[n].current_a or 0 for n in nets_of(c.ref) if n in nets] or [0])
        if cap is not None and need and cap < need:
            out.append(_f("error", "current_rating", f"{c.ref} is rated {cap:g} A but net current is {need:g} A", [c.ref]))
        if c.ref.startswith("L") and cap is None and need:
            out.append(_f("warning", "current_rating", f"{c.ref}: no saturation-current field; net carries {need:g} A — "
                                                        "record Isat (≥ 1.3× peak) from the datasheet", [c.ref]))

    # 3. pull-ups on I2C and open-drain outputs
    def has_pullup(net_name):
        for node in nets[net_name].nodes:
            ref = node.split(".", 1)[0]
            if re.match(r"^R\d", ref):
                other = [n for n in nets_of(ref) if n != net_name]
                if any(classify_net(o) == "power" or (net_voltage(nets.get(o)) or 0) > 0 for o in other):
                    return True
        return False

    for n in plan.nets:
        is_i2c = bool(re.search(r"(^|_)(SCL|SDA)(\d|_|$)", n.name.upper()))
        od = [x for x in n.nodes
              if (pins_by_ref.get(x.split(".", 1)[0], {}).get(x.split(".", 1)[1], {}).get("type") in ("open_collector",
                                                                                                    "open_emitter"))]
        if (is_i2c or od) and not has_pullup(n.name):
            why = "I2C line" if is_i2c else f"open-drain output ({', '.join(od)})"
            out.append(_f("warning", "pullup", f"Net {n.name}: {why} with no pull-up resistor to a supply", n.nodes))

    # 4. rails with more than one source → back-feed
    def is_switch_node(net_name):
        for node in nets[net_name].nodes:
            ref = node.split(".", 1)[0]
            c = comps.get(ref)
            if c and c.lib_id.startswith("Regulator_Switching"):
                return ref
        return None

    for n in plan.nets:
        if classify_net(n.name) == "ground":
            continue
        sources = []
        for node in n.nodes:
            ref, pin = node.split(".", 1)
            c = comps.get(ref)
            if not c:
                continue
            ptype = pins_by_ref.get(ref, {}).get(pin, {})
            pname = (ptype.get("name") or "").upper()
            if ptype.get("type") == "power_out" and not c.lib_id.startswith("Regulator_Switching"):
                sources.append(f"{ref} ({c.value})")
            elif ref.startswith("D") and pname in ("K", "KA", "CATHODE") and "LED" not in c.lib_id.upper() \
                    and not re.match(r"(SMAJ|SMBJ|P6KE|TVS|ESD)", c.value.upper()):
                other = [o for o in nets_of(ref) if o != n.name]
                if other and not any(is_switch_node(o) for o in other) and not any(classify_net(o) == "ground" for o in other):
                    sources.append(f"{ref} ({c.value}) from {other[0]}")
            elif ref.startswith("L"):
                other = [o for o in nets_of(ref) if o != n.name]
                reg = next((is_switch_node(o) for o in other if is_switch_node(o)), None)
                if reg:
                    sources.append(f"{reg} via {ref}")
        seen, uniq = set(), []
        for src in sources:
            if src.split()[0] not in seen:
                seen.add(src.split()[0])
                uniq.append(src)
        sources = uniq
        if len(sources) > 1:
            out.append(_f("warning", "multiple_sources",
                          f"Rail {n.name} is fed by {len(sources)} sources: {'; '.join(sources)}. When only one is "
                          "active, the others can be back-fed (e.g. into a regulator's output or through its switch "
                          "body diode into the input). Confirm each source tolerates this or add OR-ing diodes / "
                          "an ideal-diode or load switch.", [s.split()[0] for s in sources]))

    # 6. MCU pin functions: a net named like a peripheral function must sit on a pin that supports it
    from .blocks import MCU_AF
    for c in plan.components:
        if c.lib_id not in MCU_AF:
            continue
        af, generic = MCU_AF[c.lib_id]
        pname = {num: p.get("name", "") for num, p in pins_by_ref.get(c.ref, {}).items()}
        for num, name in pname.items():
            net = owner.get(f"{c.ref}.{num}")
            if not net or not re.fullmatch(r"P[A-K]\d+", name):
                continue
            base = re.sub(r"^.*/", "", net).upper()
            wanted = None
            m = re.search(r"(USB_D[PM]|USB_D[+-]|(?:SPI|I2C|USART|UART|CAN)\d_(?:SCK|MISO|MOSI|SCL|SDA|TX|RX))", base)
            if m:
                tok = m.group(1).replace("USB_D+", "USB_DP").replace("USB_D-", "USB_DM")
                if tok.startswith("UART") and tok not in af:
                    tok = "US" + tok[1:] if ("US" + tok[1:]) in af else tok
                wanted = [tok] if tok in af else None
            else:
                parts = [t for t in re.split(r"[_\-]", base) if t]
                last = re.sub(r"\d+$", "", parts[-1]) if parts else ""
                if last in ("SCL", "SDA", "SCK", "MISO", "MOSI") or (last in ("TX", "RX") and any(
                        t in ("UART", "USART", "DBG", "DEBUG", "SERIAL", "GPS", "RX", "VTX") for t in parts[:-1])):
                    wanted = generic.get(last)
            if not wanted:
                continue
            ok = [f for f in wanted if name in af[f]]
            if not ok:
                good = sorted({pin for f in wanted for pin in af[f]})
                out.append(_f("error", "mcu_pin_function",
                              f"Net {net} is on {c.ref} {name} (pin {num}), which cannot be "
                              f"{wanted[0] if len(wanted) == 1 else 'any ' + base.split('_')[-1]}: use "
                              f"{', '.join(good[:8])}{'…' if len(good) > 8 else ''}", [c.ref]))

    # 7. part rules
    def value_ohm(v):
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([kKmM]?)(\d*)", v or "")
        if not m:
            return None
        base = float(m.group(1) + ("." + m.group(3) if m.group(3) else ""))
        return base * {"k": 1e3, "K": 1e3, "M": 1e6, "m": 1e-3, "": 1}[m.group(2)]

    def value_farad(v):
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([pnuµm])", v or "")
        return float(m.group(1)) * _SI[m.group(2)] if m else None

    def two_pin_other(ref, net):
        ns = [owner.get(f"{ref}.{p}") for p in pins_by_ref.get(ref, {})]
        ns = [x for x in ns if x]
        return (ns[1] if ns[0] == net else ns[0]) if len(ns) == 2 and net in ns else None

    for c in plan.components:
        pn = pins_by_ref.get(c.ref, {})
        by_name = defaultdict(list)
        for num, p in pn.items():
            by_name[p.get("name", "")].append(f"{c.ref}.{num}")
        if "USB_C_Receptacle" in c.lib_id:
            for cc in ("CC1", "CC2"):
                for node in by_name.get(cc, []):
                    net = owner.get(node)
                    rs = [x.split(".")[0] for x in (nets[net].nodes if net else []) if re.match(r"R\d", x.split(".")[0])]
                    to_gnd = [r for r in rs if classify_net(two_pin_other(r, net) or "") == "ground"]
                    vals = [value_ohm(comps[r].value) for r in to_gnd]
                    if not to_gnd and not rs:
                        out.append(_f("error", "usb_c_cc", f"{node} ({cc}) has no resistor: a USB-C device needs 5.1 kΩ to "
                                                           "GND on each CC pin, or chargers won't turn on VBUS", [c.ref]))
                    elif to_gnd and not any(v and 4.5e3 <= v <= 5.7e3 for v in vals):
                        out.append(_f("error", "usb_c_cc", f"{node} ({cc}) pull-down is {comps[to_gnd[0]].value}: a USB-C "
                                                           "device (sink) needs 5.1 kΩ (Rd) to GND", [to_gnd[0]]))
            for sig in ("D+", "D-"):
                ns = {owner.get(x) for x in by_name.get(sig, [])}
                ns.discard(None)
                if len(ns) > 1:
                    out.append(_f("error", "usb_c_data", f"{c.ref}: the {sig} pins are on different nets ({', '.join(sorted(ns))}); "
                                                         "both rows' D+ must share one net and both D− another", [c.ref]))
            dp = {owner.get(x) for x in by_name.get("D+", [])} - {None}
            dm = {owner.get(x) for x in by_name.get("D-", [])} - {None}
            if dp & dm:
                out.append(_f("error", "usb_c_data", f"{c.ref}: D+ and D− are shorted together ({', '.join(dp & dm)})", [c.ref]))
        if c.lib_id.startswith("MCU_ST_STM32F4"):
            v1 = {owner.get(x) for x in by_name.get("VCAP_1", [])} - {None}
            v2 = {owner.get(x) for x in by_name.get("VCAP_2", [])} - {None}
            if v1 & v2:
                out.append(_f("error", "stm32_vcap", f"{c.ref}: VCAP_1 and VCAP_2 are tied together on {', '.join(v1 & v2)}; "
                                                     "each needs its own 2.2 µF capacitor to GND", [c.ref]))
            for vc in ("VCAP_1", "VCAP_2"):
                for node in by_name.get(vc, []):
                    net = owner.get(node)
                    if not net:
                        continue
                    caps = [x.split(".")[0] for x in nets[net].nodes if re.match(r"C\d", x.split(".")[0])
                            and classify_net(two_pin_other(x.split(".")[0], net) or "") == "ground"]
                    vals = [value_farad(comps[x].value) for x in caps]
                    if classify_net(net) == "power" or len(nets[net].nodes) > 2 and not caps:
                        out.append(_f("error", "stm32_vcap", f"{node} ({vc}) must only connect to its own capacitor to GND, "
                                                             f"not to {net}", [c.ref]))
                    elif not caps:
                        out.append(_f("error", "stm32_vcap", f"{node} ({vc}) needs a 2.2 µF low-ESR capacitor to GND", [c.ref]))
                    elif not any(v and 1e-6 <= v <= 4.7e-6 for v in vals):
                        out.append(_f("error", "stm32_vcap", f"{node} ({vc}) capacitor is {comps[caps[0]].value}; the internal "
                                                             "regulator needs 2.2 µF (low ESR) per VCAP pin", caps[:1]))
        if c.lib_id.startswith("Power_Protection:") and re.search(r"SP05|ESD|TPD|PESD|SRV|USBLC", c.lib_id.upper()):
            anodes = by_name.get("A", [])
            if anodes and not any(classify_net(owner.get(a) or "") == "ground" for a in anodes):
                out.append(_f("error", "tvs_orientation", f"{c.ref} ({c.value}): the common anode (pin A) must go to GND; "
                                                          f"it is on {owner.get(anodes[0])}", [c.ref]))
            gnds = by_name.get("GND", [])
            if gnds and not any(classify_net(owner.get(g) or "") == "ground" for g in gnds):
                out.append(_f("error", "tvs_orientation", f"{c.ref} ({c.value}): GND pin is not on ground", [c.ref]))

    # 8. pin role vs net: ground pins on ground, supplies/outputs not on ground; LED polarity
    for c in plan.components:
        for num, pd in pins_by_ref.get(c.ref, {}).items():
            node = f"{c.ref}.{num}"
            net = owner.get(node)
            if not net:
                continue
            name = (pd.get("name") or "").upper()
            ptype = pd.get("type", "")
            gnd_net = classify_net(net) == "ground"
            if re.fullmatch(r"(A|P|D)?GND\d*|VSS[A-Z]*|G|EP|PAD|GNDPAD", name) and ptype in ("power_in", "passive") \
                    and name not in ("G",) or (name == "G" and c.lib_id.startswith("Power_Protection")):
                if not gnd_net:
                    out.append(_f("error", "pin_role", f"{node} is the {c.value} ground pin ({pd.get('name')}) but is on "
                                                       f"{net}", [c.ref]))
            elif ptype == "power_out" and gnd_net:
                out.append(_f("error", "pin_role", f"{node} ({pd.get('name')}) is a supply OUTPUT of {c.value} but is on "
                                                   f"ground net {net} — the pins are probably swapped", [c.ref]))
            elif ptype == "power_in" and gnd_net and re.search(r"V(CC|DD|IN|I$|BAT|BUS|S$)|^IN$", name):
                out.append(_f("error", "pin_role", f"{node} ({pd.get('name')}) is a supply input of {c.value} but is on "
                                                   f"ground net {net}", [c.ref]))
        if c.lib_id.upper().startswith("DEVICE:LED") or "LED" in c.lib_id.upper().split(":")[-1][:4]:
            pn = {pd.get("name", "").upper(): f"{c.ref}.{num}" for num, pd in pins_by_ref.get(c.ref, {}).items()}
            a, k = owner.get(pn.get("A", "")), owner.get(pn.get("K", ""))
            def to_ground_via_r(net_name):
                if not net_name or net_name not in nets:
                    return False
                others = [x.split(".")[0] for x in nets[net_name].nodes if x.split(".")[0] != c.ref]
                return bool(others) and all(re.match(r"R\d", r) and classify_net(two_pin_other(r, net_name) or "") == "ground"
                                            for r in others)
            if a and (classify_net(a) == "ground" or to_ground_via_r(a)):
                out.append(_f("error", "led_polarity", f"{c.ref}: the LED anode is on {a} — it can never light. Anode goes "
                                                       "towards the supply/GPIO, cathode towards GND", [c.ref]))
            elif k and classify_net(k) == "power" and (net_voltage(nets.get(k)) or 0) > 0:
                out.append(_f("error", "led_polarity", f"{c.ref}: the LED cathode is on supply {k} — reversed", [c.ref]))

    # 9. connectivity sanity: nets that go nowhere, nets named like a pin, unconnected ground pins, block ports
    mcu_pins = {}
    for c in plan.components:
        if c.lib_id.startswith("MCU_"):
            for num, pd in pins_by_ref.get(c.ref, {}).items():
                mcu_pins.setdefault(pd.get("name", "").upper(), []).append(f"{c.ref}.{num}")
    for n in plan.nets:
        refs = {x.split(".", 1)[0] for x in n.nodes}
        if len(n.nodes) >= 2 and len(refs) == 1 and classify_net(n.name) not in ("ground", "power"):
            out.append(_f("error", "net_goes_nowhere", f"Net {n.name} only connects pins of {next(iter(refs))} "
                                                       f"({', '.join(n.nodes[:4])}) — it reaches no other part", list(refs)))
        base = re.sub(r"^.*/", "", n.name).upper()
        if re.fullmatch(r"P[A-K]\d{1,2}", base) and base in mcu_pins and not set(mcu_pins[base]) & set(n.nodes):
            out.append(_f("error", "net_named_like_pin", f"Net {n.name} is named after MCU pin {base} but does not include "
                                                         f"it ({mcu_pins[base][0]}). Naming a net doesn't connect it — add the "
                                                         "pin (or use block_connect for MCU blocks)", n.nodes[:3]))
    nc_set = set(plan.no_connect)
    for c in plan.components:
        pn = pins_by_ref.get(c.ref, {})
        used = [num for num in pn if f"{c.ref}.{num}" in owner]
        if not used:
            continue
        for num, pd in pn.items():
            node = f"{c.ref}.{num}"
            name = (pd.get("name") or "").upper()
            if node in owner or node in nc_set:
                continue
            if re.fullmatch(r"(A|P|D)?GND\d*|VSS[A-Z]*", name) or (name == "G" and c.lib_id.startswith("Power_Protection")):
                out.append(_f("error", "ground_pin_open", f"{node} ({pd.get('name')}) of {c.value} is a ground pin but is "
                                                          "not connected", [c.ref]))
        # same-name pins partly connected (VBUS, GND, VDD… on connectors and ICs)
        groups = defaultdict(list)
        for num, pd in pn.items():
            nm = pd.get("name") or ""
            if nm and nm not in ("~", "NC", "DNC") and pd.get("type") != "no_connect":
                groups[nm].append(f"{c.ref}.{num}")
        for nm, nodes in groups.items():
            if len(nodes) < 2 or nm in ("D+", "D-"):
                continue
            con = [x for x in nodes if x in owner]
            open_ = [x for x in nodes if x not in owner and x not in nc_set]
            if con and open_:
                out.append(_f("error", "partial_pin_group", f"{c.ref} ({c.value}): {len(con)} of {len(nodes)} '{nm}' pins are "
                                                            f"connected; also connect {', '.join(open_[:4])}", [c.ref]))
        # floating IC inputs
        if re.match(r"^(U|IC)\d", c.ref):
            fl = [f"{c.ref}.{num} ({pd.get('name')})" for num, pd in pn.items()
                  if pd.get("type") in ("input", "bidirectional") and f"{c.ref}.{num}" not in owner
                  and f"{c.ref}.{num}" not in nc_set]
            if fl:
                out.append(_f("warning", "floating_pin", f"{c.ref} ({c.value}): pins left unconnected: {', '.join(fl[:6])} — "
                                                         "tie them per the datasheet or mark them no-connect deliberately",
                              [c.ref]))
        if "USB_C_Receptacle" in c.lib_id:
            for sig in ("D+", "D-"):
                nodes = [f"{c.ref}.{num}" for num, pd in pn.items() if pd.get("name") == sig]
                con = [x for x in nodes if x in owner]
                if con and len(con) < len(nodes):
                    out.append(_f("error", "usb_c_data", f"{c.ref}: only {len(con)} of {len(nodes)} {sig} pins are connected "
                                                         "— the other row must be joined too or USB fails when the cable "
                                                         "is flipped", [c.ref]))
    # pins that must never be left open, whatever the no-connect flags say
    MUST = [(r"Sensor_Pressure:BMP280", {"SDO": "selects the I2C address (GND → 0x76, VDDIO → 0x77)",
                                         "CSB": "must be tied to VDDIO for I2C mode"}),
            (r"Memory_Flash:W25Q", {"IO2": "/WP — tie to VCC (or use it in quad mode)", "IO3": "/HOLD — tie to VCC"}),
            (r"MCU_ST_STM32", {"BOOT0": "pull to GND (boot from flash) or the MCU may start in the bootloader"}),
            (r"Regulator_Linear:AP2112", {"EN": "tie to VIN (or drive it) — it has no internal pull-up"}),
            (r"Regulator_Linear:(MIC5219|LP2985|LP2992|TLV7)", {"EN": "tie to VIN (or drive it)"})]
    for c in plan.components:
        for rx, rules in MUST:
            if not re.match(rx, c.lib_id):
                continue
            for num, pd in pins_by_ref.get(c.ref, {}).items():
                why = rules.get(pd.get("name", ""))
                node = f"{c.ref}.{num}"
                if why and node not in owner:
                    out.append(_f("error", "must_connect", f"{node} ({pd.get('name')}) of {c.value} is "
                                                           f"{'marked no-connect' if node in nc_set else 'unconnected'}: {why}",
                                  [c.ref]))

    # block instances: required ports must be connected
    try:
        from .blocks import BLOCKS
        by_inst = defaultdict(list)
        for c in plan.components:
            if (c.fields or {}).get("Block") and (c.fields or {}).get("BlockKey"):
                by_inst[c.block].append(c)
        import json as _json
        for inst, cs in by_inst.items():
            bid = cs[0].fields["Block"]
            params = next((_json.loads(x.fields["BlockParams"]) for x in cs if x.fields.get("BlockParams")), {})
            try:
                build = BLOCKS[bid].build(**params)
            except Exception:
                continue
            keyref = {x.fields["BlockKey"]: x.ref for x in cs}
            for pname, port in build.ports.items():
                if not port.required or port.default_net:
                    continue
                nodes_named = []
                for lp in port.pins:
                    key, pin = lp.split(".", 1)
                    ref = keyref.get(key)
                    if not ref:
                        continue
                    nums = [num for num, pd in pins_by_ref.get(ref, {}).items() if pd.get("name") == pin or num == pin]
                    nodes_named += [f"{ref}.{num}" for num in nums]
                if nodes_named and not any(x in owner and len(nets[owner[x]].nodes) > len(port.pins) for x in nodes_named):
                    out.append(_f("error", "block_port_open", f"Block {inst} ({bid}): required port {pname} is not connected "
                                                              f"to anything outside the block — "
                                                              f"block_connect(instance='{inst}', connect={{'{pname}': '<net>'}})",
                                  [x.split('.')[0] for x in nodes_named[:1]]))
    except Exception:  # noqa
        pass

    # 5. board fit from footprint sizes
    if fp_lookup and board_area_mm2:
        total, big = 0.0, []
        for c in plan.components:
            fp = fp_lookup(c.footprint) if c.footprint else None
            dims = (fp or {}).get("courtyard_mm") or [(fp or {}).get("width"), (fp or {}).get("height")]
            if not dims or not dims[0]:
                continue
            w, h = float(dims[0]), float(dims[1])
            a = (w + 0.3) * (h + 0.3)
            total += a
            if a > 0.08 * board_area_mm2:
                big.append(f"{c.ref} {w:.1f}×{h:.1f} mm ({100 * a / board_area_mm2:.0f} % of the board)")
        usable = board_area_mm2 * sides * 0.55  # routing space, holes, edge clearance
        ratio = total / usable if usable else 0
        if ratio > 1:
            out.append(_f("error", "board_fit", f"Parts need ≈{total:.0f} mm² but the board offers ≈{usable:.0f} mm² of "
                                                "usable area on {sides} side(s): make the board bigger or pick smaller parts"))
        elif ratio > 0.75:
            out.append(_f("warning", "board_fit", f"Tight: parts use ≈{100 * ratio:.0f} % of usable area ({sides} side(s)); "
                                                  "expect two-sided placement and hard routing"))
        for b in big:
            out.append(_f("info", "board_fit", f"Large part: {b} — check it fits with the connectors and mounting holes"))
    return out


def board_checks(board, plan=None, pin_lookup: Optional[Callable] = None) -> List[Dict]:
    out: List[Dict] = []
    fps = {f.ref: f for f in board.footprints}
    ics = [f for f in board.footprints if re.match(r"^(U|IC)\d", f.ref) and len(f.pads) >= 3]
    block = {c.ref: c.block for c in plan.components} if plan else {}

    def on_board(f):
        bx0, by0, bx1, by1 = board.board_bbox()
        return bx0 <= f.x <= bx1 and by0 <= f.y <= by1

    # decoupling distance: each C with GND + supply pad, nearest same-block IC supply pad on that net
    for c in board.footprints:
        if not re.match(r"^C\d", c.ref) or len(c.pads) != 2 or not on_board(c):
            continue
        nets = [p.net for p in c.pads]
        if not any(classify_net(n) == "ground" for n in nets):
            continue
        pwr = [n for n in nets if n and classify_net(n) != "ground"]
        if not pwr:
            continue
        # a regulator's output capacitor belongs at its inductor, not at a load's pin
        lpads = [q for f in board.footprints if re.match(r"^L\d", f.ref) for q in f.pads if q.net == pwr[0]]
        if lpads and min(math.hypot(p.x - q.x, p.y - q.y) for p in c.pads for q in lpads) <= 5.0:
            continue
        best = None
        for ic in ics:
            if block and block.get(ic.ref) and block.get(c.ref) and block[ic.ref] != block[c.ref]:
                continue
            for p in ic.pads:
                supply = p.pintype.startswith("power_in") or (not p.pintype and classify_net(p.net) == "power")
                if p.net == pwr[0] and supply:
                    d = min(math.hypot(p.x - q.x, p.y - q.y) for q in c.pads)
                    if best is None or d < best[0]:
                        best = (d, ic.ref, p.number)
        if best and best[0] > 5.0:
            out.append(_f("warning", "decoupling_distance", f"{c.ref} is {best[0]:.1f} mm from {best[1]} pin {best[2]} "
                                                            f"({pwr[0]}); keep decoupling within ~3 mm, same side", [c.ref, best[1]]))
    # crystals
    for f in board.footprints:
        if not re.match(r"^(Y|X)\d", f.ref) or not on_board(f):
            continue
        dmin = None
        for p in f.pads:
            if not p.net or classify_net(p.net) == "ground":
                continue
            for ic in ics:
                for q in ic.pads:
                    if q.net == p.net:
                        d = math.hypot(p.x - q.x, p.y - q.y)
                        if dmin is None or d < dmin[0]:
                            dmin = (d, ic.ref)
        if dmin and dmin[0] > 8:
            out.append(_f("warning", "crystal_distance", f"{f.ref} is {dmin[0]:.1f} mm from {dmin[1]}; keep it within ~5 mm",
                          [f.ref, dmin[1]]))
    # track width vs current
    if plan is not None:
        cur = {n.name: n.current_a for n in plan.nets if n.current_a}
        short = {}
        for t in getattr(board, "tracks", []):
            name = t.get("net") if isinstance(t, dict) else getattr(t, "net", "")
            w = t.get("width") if isinstance(t, dict) else getattr(t, "width", 0)
            layer = t.get("layer", "") if isinstance(t, dict) else getattr(t, "layer", "")
            base = name.rsplit("/", 1)[-1] if name else ""
            a = cur.get(name) or cur.get(base)
            if not a or not w:
                continue
            need = F.trace_width(current_a=a, temp_rise_c=20, layer="external" if layer in ("F.Cu", "B.Cu") else "internal")
            req = need.get("min_width_mm") or 0
            if req and w + 1e-6 < req:
                short.setdefault(name, (w, req, a))
        for name, (w, req, a) in short.items():
            out.append(_f("warning", "track_width", f"Net {name} carries {a:g} A but has {w:.2f} mm tracks; IPC-2221 "
                                                    f"(20 °C rise) wants ≥ {req:.2f} mm — widen or use a pour"))
    return out


def summarize(findings: List[Dict]) -> Dict:
    by = defaultdict(int)
    for f in findings:
        by[f["severity"]] += 1
    return {"errors": by["error"], "warnings": by["warning"], "info": by["info"]}
