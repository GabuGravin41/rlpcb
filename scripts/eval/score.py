#!/usr/bin/env python3
"""Score a data-logger plan against functional requirements (not just 'review passes')."""
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from rlpcb.agent.tools import Session, run_tool  # noqa: E402
from rlpcb.design.plan import DesignPlan  # noqa: E402

I2C = {"I2C1": [("PB6", "PB7"), ("PB8", "PB9")], "I2C2": [("PB10", "PB11")], "I2C3": [("PA8", "PC9")]}
SPI = {"SPI1": ({"PA5", "PB3"}, {"PA6", "PB4"}, {"PA7", "PB5"}), "SPI2": ({"PB10", "PB13"}, {"PB14", "PC2"}, {"PB15", "PC3"}),
       "SPI3": ({"PC10", "PB3"}, {"PC11", "PB4"}, {"PC12", "PB5"})}
UART = {"USART1": ({"PA9", "PB6"}, {"PA10", "PB7"}), "USART2": ({"PA2"}, {"PA3"}), "USART3": ({"PB10", "PC10"}, {"PB11", "PC11"}),
        "UART4": ({"PA0", "PC10"}, {"PA1", "PC11"}), "UART5": ({"PC12"}, {"PD2"}), "USART6": ({"PC6"}, {"PC7"})}


def score(project_dir):
    s = Session()
    pro = os.path.join(project_dir, "board", "board.kicad_pro")
    run_tool(s, "open_project", {"path": pro})
    plan = DesignPlan.load(os.path.dirname(pro))
    owner = plan.node_net()
    comps = {c.ref: c for c in plan.components}
    pins = {c.ref: {p["number"]: p for p in s.pins_of(c.lib_id)} for c in plan.components}
    nets = defaultdict(list)
    for n in plan.nets:
        nets[n.name] = n.nodes

    def named(ref, rx):
        return [f"{ref}.{num}" for num, p in pins.get(ref, {}).items() if re.fullmatch(rx, p.get("name", ""), re.I)]

    def net_of(node):
        return owner.get(node)

    def find(pred):
        return [r for r, c in comps.items() if pred(c)]

    def is_gnd(net):
        return bool(net) and re.search(r"GND|VSS", net, re.I) is not None

    def two_pin_other(ref, net):
        ns = [owner.get(f"{ref}.{p}") for p in pins.get(ref, {})]
        ns = [x for x in ns if x]
        if len(ns) == 2 and net in ns:
            return ns[1] if ns[0] == net else ns[0]
        return None

    def parts_on(net, prefix):
        return [x.split(".")[0] for x in nets.get(net, []) if re.match(prefix, x.split(".")[0])]

    def cap_to_gnd(net):
        return any(is_gnd(two_pin_other(c, net)) for c in parts_on(net, r"C\d"))

    def res_to(net, pred):
        return any(pred(two_pin_other(r, net)) for r in parts_on(net, r"R\d"))

    # merge nets through pass-through parts
    parent = {}

    def fnd(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def uni(a, b):
        if a and b:
            parent[fnd(a)] = fnd(b)

    for r, c in comps.items():
        if "USBLC6" in c.lib_id.upper() or "USBLC6" in c.value.upper():
            uni(owner.get(f"{r}.1"), owner.get(f"{r}.6"))
            uni(owner.get(f"{r}.3"), owner.get(f"{r}.4"))
        elif re.match(r"R\d", r) and re.match(r"^(0|22|27|33|47)(R|Ω|ohm)?$", c.value.strip(), re.I):
            ns = [owner.get(f"{r}.1"), owner.get(f"{r}.2")]
            uni(*ns)
    ppar = dict()

    def pfind(x):
        ppar.setdefault(x, x)
        while ppar[x] != x:
            x = ppar[x]
        return x

    for r, c in comps.items():
        if re.match(r"(D|FB|F|L)\d", r) and "LED" not in c.lib_id.upper() and len(pins.get(r, {})) == 2:
            a, b = owner.get(f"{r}.1"), owner.get(f"{r}.2")
            if a and b and not is_gnd(a) and not is_gnd(b):
                ppar[pfind(a)] = pfind(b)

    res = {}
    mcu = next(iter(find(lambda c: "STM32F405" in c.lib_id)), None)
    res["mcu_present"] = bool(mcu)
    if not mcu:
        return res, 0
    gpio = {}  # pin name -> net
    for num, p in pins[mcu].items():
        gpio[p["name"]] = owner.get(f"{mcu}.{num}")
    v33 = {n for n in (gpio.get("VDD") and [owner.get(x) for x in named(mcu, "VDD")] or []) if n}
    res["mcu_power"] = bool(v33) and all(owner.get(x) and not is_gnd(owner.get(x)) for x in named(mcu, "VDD|VBAT|VDDA")) \
        and len(v33) == 1
    rail = next(iter(v33)) if len(v33) == 1 else None
    res["mcu_ground"] = all(is_gnd(owner.get(x)) for x in named(mcu, "VSS|VSSA"))
    def vcap_ok(net):
        for c in parts_on(net, r"C\d"):
            m = re.match(r"^(\d+(?:\.\d+)?)\s*u", comps[c].value.strip().replace("µ", "u"))
            if is_gnd(two_pin_other(c, net)) and m and 1.0 <= float(m.group(1)) <= 4.7:
                return True
        return False
    res["vcap"] = all(owner.get(x) and owner.get(x) != rail and vcap_ok(owner.get(x)) for x in named(mcu, "VCAP_[12]"))
    b0 = gpio.get("BOOT0")
    res["boot0"] = bool(b0) and (is_gnd(b0) or res_to(b0, is_gnd))
    ph0, ph1 = gpio.get("PH0"), gpio.get("PH1")
    res["hse_crystal"] = bool(ph0 and ph1) and bool(parts_on(ph0, r"Y\d")) and bool(parts_on(ph1, r"Y\d")) and \
        cap_to_gnd(ph0) and cap_to_gnd(ph1)
    res["decoupling"] = bool(rail) and sum(1 for c in parts_on(rail, r"C\d") if is_gnd(two_pin_other(c, rail))) >= 4
    usb = next(iter(find(lambda c: "USB_C" in c.lib_id.upper())), None)
    ok_usb = False
    if usb:
        dp = [owner.get(x) for x in named(usb, r"D\+")]
        dm = [owner.get(x) for x in named(usb, r"D-")]
        ok_usb = bool(dp and dm and gpio.get("PA12") and gpio.get("PA11")) and \
            all(d and fnd(d) == fnd(gpio["PA12"]) for d in dp) and all(d and fnd(d) == fnd(gpio["PA11"]) for d in dm)
    res["usb_data"] = ok_usb
    def rd_ok(net):
        for r in parts_on(net, r"R\d"):
            v = comps[r].value.strip().lower().replace("Ω", "").replace("ohm", "")
            if is_gnd(two_pin_other(r, net)) and re.match(r"^(5\.1k|5k1|5\.1\s*k|5100)", v):
                return True
        return False
    res["usb_cc"] = bool(usb) and all(owner.get(x) and rd_ok(owner.get(x)) for x in named(usb, "CC[12]"))
    esd_ok = False
    for r, c in comps.items():
        if c.lib_id.startswith("Power_Protection:"):
            ann = named(r, "A") + named(r, "GND") + named(r, "G")
            esd_ok = bool(ann) and all(is_gnd(owner.get(x)) for x in ann)
    res["usb_esd"] = esd_ok
    ldo = next(iter(find(lambda c: c.lib_id.startswith("Regulator_Linear"))), None)
    ok_pp = False
    if usb and ldo:
        vbus = [owner.get(x) for x in named(usb, "VBUS")]
        vin = [owner.get(x) for x in named(ldo, "VIN|VI|IN")]
        vout = [owner.get(x) for x in named(ldo, "VOUT|VO|OUT")]
        ok_pp = bool(vbus and vin and vout) and all(v and pfind(v) == pfind(vin[0]) for v in vbus) and vout[0] == rail
    res["power_path"] = ok_pp
    res["ldo_caps"] = bool(ldo) and all(owner.get(x) and cap_to_gnd(owner.get(x)) for x in named(ldo, "VIN|VI|VOUT|VO"))
    baro = next(iter(find(lambda c: "BMP280" in c.lib_id)), None)
    ok_i2c = False
    if baro:
        scl, sda = owner.get(named(baro, "SCK")[0]) if named(baro, "SCK") else None, owner.get(named(baro, "SDI")[0]) if named(baro, "SDI") else None
        for pairs in I2C.values():
            for a, b in pairs:
                if scl and sda and gpio.get(a) == scl and gpio.get(b) == sda:
                    ok_i2c = True
        res["i2c_pullups"] = bool(scl and sda) and res_to(scl, lambda n: n == rail) and res_to(sda, lambda n: n == rail)
        csb = owner.get(named(baro, "CSB")[0]) if named(baro, "CSB") else None
        sdo = owner.get(named(baro, "SDO")[0]) if named(baro, "SDO") else None
        res["baro_mode"] = csb == rail and (is_gnd(sdo) or sdo == rail) and \
            all(owner.get(x) == rail for x in named(baro, "VDD|VDDIO")) and all(is_gnd(owner.get(x)) for x in named(baro, "GND"))
    else:
        res["i2c_pullups"] = res["baro_mode"] = False
    res["i2c_pins"] = ok_i2c
    fl = next(iter(find(lambda c: "W25Q" in c.lib_id.upper())), None)
    ok_spi = False
    if fl:
        def fnet(rx):
            x = named(fl, rx)
            return owner.get(x[0]) if x else None
        clk, di, do, cs = fnet("CLK"), fnet(r"DI.*|IO0.*"), fnet(r"DO.*|IO1.*"), fnet(r"~?\{?CS\}?|/CS|CS")
        for sck, miso, mosi in SPI.values():
            if any(gpio.get(p) == clk for p in sck) and any(gpio.get(p) == do for p in miso) and \
                    any(gpio.get(p) == di for p in mosi) and clk and do and di:
                ok_spi = True
        ok_spi = ok_spi and bool(cs) and any(v == cs for k, v in gpio.items() if re.fullmatch(r"P[A-D]\d+", k))
        res["flash_misc"] = all(owner.get(x) == rail or (owner.get(x) and res_to(owner.get(x), lambda n: n == rail))
                                for x in named(fl, r".*IO2.*|.*IO3.*|.*WP.*|.*HOLD.*")) and \
            all(owner.get(x) == rail for x in named(fl, "VCC")) and cap_to_gnd(rail)
    else:
        res["flash_misc"] = False
    res["flash_spi"] = ok_spi
    ok_led = False
    for d in find(lambda c: "LED" in c.lib_id.upper()):
        ns = [owner.get(f"{d}.{p}") for p in pins.get(d, {})]
        if any(is_gnd(n) for n in ns):
            other = next((n for n in ns if n and not is_gnd(n)), None)
            if other and parts_on(other, r"R\d"):
                r_other = [two_pin_other(r, other) for r in parts_on(other, r"R\d")]
                ok_led = any(o == rail or o in gpio.values() for o in r_other)
        elif all(ns):  # LED between a GPIO/rail and a resistor to GND
            ok_led = any(parts_on(n, r"R\d") for n in ns)
    res["led"] = ok_led
    ok_uart = False
    for j in find(lambda c: c.ref.startswith("J") and c.ref != usb):
        jn = {owner.get(x) for x in [f"{j}.{p}" for p in pins.get(j, {})]}
        if not any(is_gnd(n) for n in jn):
            continue
        for tx, rx in UART.values():
            if any(gpio.get(p) in jn for p in tx if gpio.get(p)) and any(gpio.get(p) in jn for p in rx if gpio.get(p)):
                ok_uart = True
    res["uart_header"] = ok_uart
    rv = run_tool(s, "plan_review", {})
    res["review_clean"] = not rv.get("errors")
    return res, sum(bool(v) for v in res.values())


if __name__ == "__main__":
    out = {}
    for d in sys.argv[1:]:
        r, n = score(d)
        calls = sum(1 for _ in open(os.path.join(d, "calls.log"))) if os.path.exists(os.path.join(d, "calls.log")) else None
        out[d] = {"score": f"{n}/{len(r)}", "failed": [k for k, v in r.items() if not v], "tool_calls": calls}
    print(json.dumps(out, indent=1))
