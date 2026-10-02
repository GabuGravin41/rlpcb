"""Pre-verified circuit blocks.

A block is a parameterised sub-circuit whose internal wiring, part choices and values have been checked once (against
the datasheet's typical application and by building a board with it). A model using blocks only chooses blocks, sets a
few parameters and connects *ports* — e.g. ``{"VOUT": "+5V", "GND": "GND"}``, or for an MCU peripheral functions
such as ``{"SPI1_SCK": "IMU_SCK", "USART1_TX": "RX_TX"}`` instead of pin numbers. That removes most of the places a
weaker model can go wrong: pin names, decoupling, feedback networks, crystal loads, alternate-function pins.

Every block returns the calculations it made (with formulas) and the datasheet points a human should still confirm.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from ..calc import formulas as F

R0402, C0402, C0603, C0805, C1206 = ("Resistor_SMD:R_0402_1005Metric", "Capacitor_SMD:C_0402_1005Metric",
                                     "Capacitor_SMD:C_0603_1608Metric", "Capacitor_SMD:C_0805_2012Metric",
                                     "Capacitor_SMD:C_1206_3216Metric")
CAP_RATINGS = [6.3, 10, 16, 25, 35, 50, 63, 100]


def cap_rating(v_max: float, margin: float = 1.5) -> float:
    """Smallest standard ceramic voltage rating ≥ margin × working voltage (DC-bias derating)."""
    for r in CAP_RATINGS:
        if r >= v_max * margin:
            return r
    return CAP_RATINGS[-1]


def si(v: float, unit: str = "") -> str:
    """Compact KiCad-style value: 9310 → 9.31k, 1.8e-11 → 18p."""
    if v == 0:
        return "0" + unit
    for exp, p in ((1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m"), (1e-6, "u"), (1e-9, "n"), (1e-12, "p")):
        if abs(v) >= exp * 0.9999:
            x = v / exp
            s = f"{x:.3g}"
            return s + p + unit
    return f"{v:g}{unit}"


@dataclass
class Port:
    pins: List[str]                  # local pins "key.PIN"
    kind: str = "signal"             # power_in | power_out | ground | signal | analog | diff_pair
    required: bool = True
    desc: str = ""
    default_net: str = ""            # used when the caller does not map the port
    tie_to: str = ""                 # if unmapped: tie to this other port's net
    net_attrs: Dict = field(default_factory=dict)


@dataclass
class BlockBuild:
    parts: List[Dict]                # {key, prefix, lib_id, value, footprint, role, fields}
    nets: List[Tuple[str, List[str], Dict]]  # internal nets (local name, pins, attrs)
    ports: Dict[str, Port]
    nc: List[str] = field(default_factory=list)
    calculations: List[Dict] = field(default_factory=list)
    confirm: List[str] = field(default_factory=list)   # datasheet points a human must check
    layout: str = ""


@dataclass
class BlockDef:
    id: str
    title: str
    category: str
    params: Dict[str, Dict]          # name -> {default, desc, min?, max?}
    build: Callable[..., BlockBuild]
    summary: str = ""


BLOCKS: Dict[str, BlockDef] = {}


def block(id, title, category, params, summary=""):
    def deco(fn):
        BLOCKS[id] = BlockDef(id, title, category, params, fn, summary)
        return fn
    return deco


def P(key, prefix, lib_id, value, footprint, role, **fields):
    return {"key": key, "prefix": prefix, "lib_id": lib_id, "value": value, "footprint": footprint, "role": role,
            "fields": {k: str(v) for k, v in fields.items()}}


# =============================================================================== power
@block("tps5430_buck", "Buck converter 5.5–36 V in, up to 3 A (TI TPS5430, 500 kHz)", "power",
       {"vin_min": {"default": 7.0, "desc": "Minimum input voltage (V), ≥ 5.5"},
        "vin_max": {"default": 25.2, "desc": "Maximum input voltage (V), ≤ 36"},
        "vout": {"default": 5.0, "desc": "Output voltage (V), 1.22–(0.87·Vin_min)"},
        "iout": {"default": 2.0, "desc": "Maximum load current (A), ≤ 3"}},
       "Datasheet typical application: input caps, bootstrap cap, Schottky catch diode, inductor, output caps, "
       "feedback divider to the 1.221 V reference.")
def _buck(vin_min=7.0, vin_max=25.2, vout=5.0, iout=2.0):
    if not (5.5 <= vin_min <= vin_max <= 36):
        raise ValueError("TPS5430 needs 5.5 V ≤ vin_min ≤ vin_max ≤ 36 V")
    if not (1.23 <= vout <= 0.87 * vin_min):
        raise ValueError(f"vout must be between 1.23 V and 0.87·vin_min = {0.87 * vin_min:.2f} V (max duty cycle)")
    if iout > 3:
        raise ValueError("TPS5430 is a 3 A part; use a bigger converter for > 3 A")
    fb = F.divider(vout=vout, vref=1.221, series="E96", r_total_target=13e3)
    st = F.buck(vin_min=vin_min, vin_max=vin_max, vout=vout, iout=iout, fsw_hz=500e3, ripple_ratio=0.3)
    L = F.nearest_e(st["inductor_h"], "E6")["nearest"]
    isat = st["inductor_saturation_min_a"]
    l_fp = "Inductor_SMD:L_Bourns_SRP7028A_7.3x6.6mm" if isat <= 4.5 else "Inductor_SMD:L_Bourns_SRP1038C_10.0x10.0mm"
    cin_v, cout_v = cap_rating(vin_max), cap_rating(vout)
    diode_v = 40 if vin_max <= 30 else 60
    diode = ("Diode:B340", "B340A") if diode_v == 40 else ("Diode:B360", "B360A")
    parts = [
        P("U", "U", "Regulator_Switching:TPS5430DDA", "TPS5430", "", "Buck regulator (TPS5430, 500 kHz)"),
        P("CIN1", "C", "Device:C", f"10u {cin_v:g}V", C1206, "Input cap — hot loop, next to VIN/GND", Voltage=f"{cin_v:g}V", Dielectric="X7R"),
        P("CIN2", "C", "Device:C", f"10u {cin_v:g}V", C1206, "Input cap", Voltage=f"{cin_v:g}V", Dielectric="X7R"),
        P("CBOOT", "C", "Device:C", "10n", C0402, "Bootstrap cap BOOT–PH", Voltage="25V"),
        P("D", "D", diode[0], diode[1], "Diode_SMD:D_SMA", f"Catch diode ({diode_v} V, 3 A Schottky)", Voltage=f"{diode_v}V"),
        P("L", "L", "Device:L", si(L), l_fp,
          f"Inductor — calc {st['inductor']}, Isat ≥ {isat} A", Isat_min=f"{isat}A", Current=f"{iout}A"),
        P("COUT1", "C", "Device:C", f"22u {cout_v:g}V", C0805, "Output cap", Voltage=f"{cout_v:g}V", Dielectric="X5R"),
        P("COUT2", "C", "Device:C", f"22u {cout_v:g}V", C0805, "Output cap", Voltage=f"{cout_v:g}V", Dielectric="X5R"),
        P("RFB1", "R", "Device:R", si(fb["R1_top_ohm"]), R0402, f"Feedback top: Vout = 1.221·(1+R1/R2) = {fb['actual_output_v']} V"),
        P("RFB2", "R", "Device:R", si(fb["R2_bottom_ohm"]), R0402, "Feedback bottom"),
    ]
    nets = [("SW", ["U.PH", "D.K", "L.1", "CBOOT.2"], {"current_a": round(st["inductor_peak_a"], 2),
                                                      "notes": "Switch node: short and wide, away from sensitive circuits"}),
            ("BOOT", ["U.BOOT", "CBOOT.1"], {}),
            ("FB", ["U.VSENSE", "RFB1.2", "RFB2.1"], {"notes": "Keep away from the switch node"})]
    ports = {
        "VIN": Port(["U.VIN", "CIN1.1", "CIN2.1"], "power_in", desc="Input rail",
                    net_attrs={"net_class": "power", "voltage_v": vin_max, "current_a": round(iout * vout / (0.85 * vin_min), 2)}),
        "VOUT": Port(["L.2", "COUT1.1", "COUT2.1", "RFB1.1"], "power_out", desc="Regulated output",
                     net_attrs={"net_class": "power", "voltage_v": vout, "current_a": iout}),
        "GND": Port(["U.GND", "U.GNDPAD", "CIN1.2", "CIN2.2", "D.A", "COUT1.2", "COUT2.2", "RFB2.2"], "ground",
                    default_net="GND", net_attrs={"net_class": "ground"}),
        "EN": Port(["U.EN"], "signal", required=False, desc="Enable (internal pull-up; leave unconnected = on)"),
    }
    return BlockBuild(parts, nets, ports, nc=["U.NC"],
                      calculations=[{"feedback_divider": fb}, {"power_stage": {k: st[k] for k in (
                          "duty_range", "inductor", "inductor_nearest_E6", "inductor_peak_a", "inductor_saturation_min_a",
                          "cout_min", "cin_rms_current_a", "method")}}],
                      confirm=[f"Inductor: pick a part with Isat ≥ {isat} A and Irms ≥ {iout} A (footprint {l_fp.split(':')[1]}).",
                               "Input caps: X7R, rated ≥ 1.5× Vin_max; check DC-bias derating on the datasheet.",
                               "USB-powered boards: 5 V can back-feed VIN through the high-side switch body diode."],
                      layout="Hot loop CIN–U–D as small as possible on one layer; GND pad with thermal vias; FB divider next to "
                             "VSENSE, routed away from the SW node and L.")


@block("ldo_3v3", "3.3 V LDO, 600 mA (Diodes AP2112K-3.3)", "power",
       {"vin_max": {"default": 5.0, "desc": "Maximum input voltage (V), ≤ 6"},
        "iout": {"default": 0.4, "desc": "Load current (A), ≤ 0.6"}},
       "Input 1 µF, output 4.7 µF ceramic; EN tied to VIN unless mapped.")
def _ldo(vin_max=5.0, iout=0.4):
    if vin_max > 6:
        raise ValueError("AP2112K is rated for 6 V input; put a buck in front of it")
    if iout > 0.6:
        raise ValueError("AP2112K is a 600 mA part")
    th = F.ldo(vin=vin_max, vout=3.3, iout=iout, theta_ja_c_per_w=250)
    parts = [P("U", "U", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3", "", "3.3 V LDO"),
             P("CIN", "C", "Device:C", "1u", C0402, "LDO input cap", Voltage=f"{cap_rating(vin_max):g}V"),
             P("COUT", "C", "Device:C", "4.7u", C0603, "LDO output cap / 3.3 V bulk", Voltage="10V")]
    ports = {"VIN": Port(["U.VIN", "CIN.1"], "power_in", net_attrs={"net_class": "power", "voltage_v": vin_max}),
             "VOUT": Port(["U.VOUT", "COUT.1"], "power_out", net_attrs={"net_class": "power", "voltage_v": 3.3, "current_a": iout}),
             "GND": Port(["U.GND", "CIN.2", "COUT.2"], "ground", default_net="GND", net_attrs={"net_class": "ground"}),
             "EN": Port(["U.EN"], "signal", required=False, tie_to="VIN", desc="Enable; tied to VIN if not mapped")}
    return BlockBuild(parts, [], ports, nc=["U.NC"], calculations=[{"ldo_thermal": th}],
                      confirm=[f"LDO dissipation {th.get('power_w', '?')} W in SOT-23-5 — check temperature rise."],
                      layout="Caps within 2 mm of the pins.")


@block("battery_input", "Battery input pads with TVS clamp", "power",
       {"vmax": {"default": 25.2, "desc": "Maximum battery voltage (V)"}},
       "Solder pads + unidirectional TVS (standoff above vmax).")
def _bat(vmax=25.2):
    tvs = [(5.0, "SMAJ5.0A"), (12, "SMAJ12A"), (15, "SMAJ15A"), (18, "SMAJ18A"), (24, "SMAJ24A"), (28, "SMAJ28A"),
           (33, "SMAJ33A"), (40, "SMAJ40A")]
    pick = next((t for t in tvs if t[0] >= vmax * 1.05), tvs[-1])
    parts = [P("J", "J", "Connector_Generic:Conn_01x02", "BATT", "Connector_Wire:SolderWire-1.5sqmm_1x02_P6mm_D1.7mm_OD3mm",
               "Battery pads (1 = +, 2 = −)"),
             P("TVS", "D", "Diode:SMAJ28A", pick[1], "Diode_SMD:D_SMA", f"TVS clamp, {pick[0]} V standoff > {vmax} V",
               Voltage=f"{pick[0]}V")]
    ports = {"VBAT": Port(["J.1", "TVS.1"], "power_out", net_attrs={"net_class": "power", "voltage_v": vmax}),
             "GND": Port(["J.2", "TVS.2"], "ground", default_net="GND", net_attrs={"net_class": "ground"})}
    return BlockBuild(parts, [], ports, confirm=[f"{pick[1]}: check the symbol's pin 1 is the cathode (to VBAT)."],
                      layout="TVS right behind the pads; wide copper.")


@block("voltage_divider_adc", "Voltage-sense divider for an ADC input, with filter cap", "analog",
       {"vmax": {"default": 25.2, "desc": "Maximum measured voltage (V)"},
        "adc_max": {"default": 3.3, "desc": "ADC full scale (V)"}},
       "Divider sized so vmax reads at ~70 % of full scale; 100 nF filter at the ADC pin.")
def _vdiv(vmax=25.2, adc_max=3.3):
    d = F.divider(vout=0.7 * adc_max, vin=vmax, series="E24", r_total_target=11e3)
    parts = [P("RTOP", "R", "Device:R", si(d["R1_top_ohm"]), R0402, f"Divider top ({vmax} V → {d['actual_output_v']} V)"),
             P("RBOT", "R", "Device:R", si(d["R2_bottom_ohm"]), R0402, "Divider bottom"),
             P("C", "C", "Device:C", "100n", C0402, "ADC filter", Voltage="16V")]
    ports = {"IN": Port(["RTOP.1"], "power_in"), "OUT": Port(["RTOP.2", "RBOT.1", "C.1"], "analog",
                                                              net_attrs={"net_class": "analog"}),
             "GND": Port(["RBOT.2", "C.2"], "ground", default_net="GND")}
    return BlockBuild(parts, [], ports, calculations=[{"divider": d}])


# =============================================================================== MCU
# STM32F405RGTx: default alternate-function pin for each peripheral signal (LQFP-64).
F405_FUNCTIONS = {
    "USB_DM": "PA11", "USB_DP": "PA12", "SWDIO": "PA13", "SWCLK": "PA14",
    "SPI1_SCK": "PA5", "SPI1_MISO": "PA6", "SPI1_MOSI": "PA7",
    "SPI2_SCK": "PB13", "SPI2_MISO": "PB14", "SPI2_MOSI": "PB15",
    "SPI3_SCK": "PC10", "SPI3_MISO": "PC11", "SPI3_MOSI": "PC12",
    "I2C1_SCL": "PB8", "I2C1_SDA": "PB9", "I2C2_SCL": "PB10", "I2C2_SDA": "PB11",
    "USART1_TX": "PA9", "USART1_RX": "PA10", "USART2_TX": "PA2", "USART2_RX": "PA3",
    "USART3_TX": "PB10", "USART3_RX": "PB11", "UART4_TX": "PA0", "UART4_RX": "PA1",
    "USART6_TX": "PC6", "USART6_RX": "PC7",
    "TIM3_CH1": "PB4", "TIM3_CH2": "PB5", "TIM3_CH3": "PB0", "TIM3_CH4": "PB1",
    "TIM5_CH3": "PA2", "TIM5_CH4": "PA3", "TIM8_CH1": "PC6", "TIM8_CH2": "PC7", "TIM4_CH1": "PB6", "TIM4_CH2": "PB7",
    "CAN1_RX": "PB8", "CAN1_TX": "PB9",
    "ADC_IN0": "PA0", "ADC_IN1": "PA1", "ADC_IN4": "PA4", "ADC_IN8": "PB0", "ADC_IN9": "PB1",
    "ADC_IN10": "PC0", "ADC_IN11": "PC1", "ADC_IN12": "PC2", "ADC_IN13": "PC3", "ADC_IN14": "PC4", "ADC_IN15": "PC5",
}
# Every pin that can carry each function on the STM32F405 LQFP-64 (datasheet AF table, common peripherals).
F405_AF = {
    "USB_DP": {"PA12"}, "USB_DM": {"PA11"}, "SWDIO": {"PA13"}, "SWCLK": {"PA14"},
    "SPI1_SCK": {"PA5", "PB3"}, "SPI1_MISO": {"PA6", "PB4"}, "SPI1_MOSI": {"PA7", "PB5"},
    "SPI2_SCK": {"PB10", "PB13"}, "SPI2_MISO": {"PB14", "PC2"}, "SPI2_MOSI": {"PB15", "PC3"},
    "SPI3_SCK": {"PC10", "PB3"}, "SPI3_MISO": {"PC11", "PB4"}, "SPI3_MOSI": {"PC12", "PB5"},
    "I2C1_SCL": {"PB6", "PB8"}, "I2C1_SDA": {"PB7", "PB9"}, "I2C2_SCL": {"PB10"}, "I2C2_SDA": {"PB11"},
    "I2C3_SCL": {"PA8"}, "I2C3_SDA": {"PC9"},
    "USART1_TX": {"PA9", "PB6"}, "USART1_RX": {"PA10", "PB7"}, "USART2_TX": {"PA2"}, "USART2_RX": {"PA3"},
    "USART3_TX": {"PB10", "PC10"}, "USART3_RX": {"PB11", "PC11"}, "UART4_TX": {"PA0", "PC10"}, "UART4_RX": {"PA1", "PC11"},
    "UART5_TX": {"PC12"}, "UART5_RX": {"PD2"}, "USART6_TX": {"PC6"}, "USART6_RX": {"PC7"},
    "CAN1_RX": {"PB8", "PA11"}, "CAN1_TX": {"PB9", "PA12"}, "CAN2_RX": {"PB5", "PB12"}, "CAN2_TX": {"PB6", "PB13"},
}
# generic net-name tokens → the set of function names that satisfy them
F405_GENERIC = {
    "USB_DP": ["USB_DP"], "USB_DM": ["USB_DM"], "USB_D+": ["USB_DP"], "USB_D-": ["USB_DM"],
    "SCL": [k for k in F405_AF if k.endswith("_SCL")], "SDA": [k for k in F405_AF if k.endswith("_SDA")],
    "TX": [k for k in F405_AF if k.endswith("_TX") and "CAN" not in k], "RX": [k for k in F405_AF if k.endswith("_RX") and "CAN" not in k],
    "SCK": [k for k in F405_AF if k.endswith("_SCK")], "MISO": [k for k in F405_AF if k.endswith("_MISO")],
    "MOSI": [k for k in F405_AF if k.endswith("_MOSI")],
}
MCU_AF = {"MCU_ST_STM32F4:STM32F405RGTx": (F405_AF, F405_GENERIC)}

F405_GPIO = [f"P{b}{i}" for b, n in (("A", 16), ("B", 16), ("C", 16)) for i in range(n)] + ["PD2", "PH0", "PH1"]
F405_RESERVED = {"PH0", "PH1", "PA13", "PA14"}  # HSE crystal and SWD (used by the block itself)


@block("stm32f405_core", "STM32F405RGT6 core (168 MHz Cortex-M4F, LQFP-64)", "mcu",
       {"hse_mhz": {"default": 8, "desc": "HSE crystal frequency (MHz)"},
        "crystal_cl_pf": {"default": 12, "desc": "Crystal load capacitance from its datasheet (pF)"},
        "boot_button": {"default": True, "desc": "Add a BOOT0 push-button (hold at power-up for USB DFU)"}},
       "Four 100 nF + 4.7 µF on VDD, 2×2.2 µF VCAP, ferrite + 1 µF/100 nF on VDDA, HSE crystal with calculated load "
       "caps, NRST filter, BOOT0 pull-down (+ button). Connect peripherals by function name (SPI1_SCK, USART1_TX, "
       "USB_DP, ADC_IN12, TIM3_CH3…) or any GPIO name (PB5). Unused GPIOs get no-connect flags.")
def _f405(hse_mhz=8, crystal_cl_pf=12, boot_button=True):
    lc = F.crystal_load_caps(cl_pf=float(crystal_cl_pf))
    cl = lc["nearest_E12_pf"]
    parts = [P("U", "U", "MCU_ST_STM32F4:STM32F405RGTx", "STM32F405RGT6", "", "MCU"),
             *[P(f"CD{i}", "C", "Device:C", "100n", C0402, f"VDD pin {pin} decoupling", Voltage="16V")
               for i, pin in enumerate(("19", "32", "48", "64"), 1)],
             P("CBULK", "C", "Device:C", "4.7u", C0603, "VDD bulk", Voltage="10V"),
             P("CVCAP1", "C", "Device:C", "2.2u", C0402, "VCAP_1 (low-ESR, required by the internal regulator)", Voltage="10V"),
             P("CVCAP2", "C", "Device:C", "2.2u", C0402, "VCAP_2", Voltage="10V"),
             P("FB", "FB", "Device:FerriteBead_Small", "600R@100MHz", "Inductor_SMD:L_0603_1608Metric", "VDDA filter"),
             P("CA1", "C", "Device:C", "1u", C0402, "VDDA bulk", Voltage="10V"),
             P("CA2", "C", "Device:C", "100n", C0402, "VDDA HF", Voltage="16V"),
             P("Y", "Y", "Device:Crystal_GND24", f"{hse_mhz}MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
               f"HSE {hse_mhz} MHz, CL {crystal_cl_pf} pF"),
             P("CX1", "C", "Device:C", f"{cl:g}p", C0402, f"Crystal load: 2·(CL−Cstray) = {lc['each_cap_pf']} pF", Voltage="50V"),
             P("CX2", "C", "Device:C", f"{cl:g}p", C0402, "Crystal load", Voltage="50V"),
             P("CRST", "C", "Device:C", "100n", C0402, "NRST filter", Voltage="16V"),
             P("RBOOT", "R", "Device:R", "10k", R0402, "BOOT0 pull-down (run from flash)")]
    if boot_button:
        parts.append(P("SW", "SW", "Switch:SW_Push", "BOOT", "Button_Switch_SMD:SW_SPST_TL3342",
                       "Hold at power-up for the USB DFU bootloader"))
    nets = [("VCAP1", ["U.VCAP_1", "CVCAP1.1"], {}), ("VCAP2", ["U.VCAP_2", "CVCAP2.1"], {}),
            ("VDDA", ["FB.2", "U.VDDA", "CA1.1", "CA2.1"], {"net_class": "analog"}),
            ("OSC_IN", ["U.PH0", "Y.1", "CX1.1"], {}), ("OSC_OUT", ["U.PH1", "Y.3", "CX2.1"], {}),
            ("NRST", ["U.NRST", "CRST.1"], {}), ("BOOT0", ["U.BOOT0", "RBOOT.1"] + (["SW.1"] if boot_button else []), {})]
    vdd = ["U.VDD", "U.VBAT", "FB.1", "CBULK.1"] + [f"CD{i}.1" for i in range(1, 5)] + (["SW.2"] if boot_button else [])
    gnd = ["U.VSS", "U.VSSA", "CBULK.2", "CVCAP1.2", "CVCAP2.2", "CA1.2", "CA2.2", "Y.2", "Y.4", "CX1.2", "CX2.2",
           "CRST.2", "RBOOT.2"] + [f"CD{i}.2" for i in range(1, 5)]
    ports = {"VDD": Port(vdd, "power_in", desc="3.3 V supply", net_attrs={"net_class": "power"}),
             "GND": Port(gnd, "ground", default_net="GND", net_attrs={"net_class": "ground"}),
             "SWDIO": Port(["U.PA13"], "signal", required=False), "SWCLK": Port(["U.PA14"], "signal", required=False),
             "NRST": Port(["U.NRST"], "signal", required=False, desc="Reset (for a debug connector)")}
    # any GPIO, and function aliases, are optional ports; resolved in _mcu_port()
    return BlockBuild(parts, nets, ports, calculations=[{"crystal_load_caps": lc}],
                      confirm=[f"Crystal: confirm its load capacitance is {crystal_cl_pf} pF; caps are {cl:g} pF.",
                               "Check every function→pin choice against the reference manual's alternate-function table "
                               "if you use peripherals beyond the ones listed by list_blocks."],
                      layout="One 100 nF per VDD pin, on the same side, < 2 mm away; crystal + load caps within 5 mm of "
                             "PH0/PH1 with ground pour under them; VCAP caps at their pins.")


BLOCK_GPIO = {"stm32f405_core": (F405_FUNCTIONS, F405_GPIO, F405_RESERVED)}


# =============================================================================== sensors / memory
@block("icm20602_spi", "6-axis IMU on SPI (TDK ICM-20602) with filtered supply", "sensor", {},
       "Ferrite-isolated supply, 100 nF on VDD/VDDIO/REGOUT + 2.2 µF bulk, FSYNC grounded.")
def _imu():
    parts = [P("U", "U", "Sensor_Motion:ICM-20602", "ICM-20602", "", "6-axis IMU (SPI)"),
             P("FB", "FB", "Device:FerriteBead_Small", "600R@100MHz", "Inductor_SMD:L_0603_1608Metric", "Isolates the IMU supply"),
             P("C1", "C", "Device:C", "100n", C0402, "VDD", Voltage="16V"),
             P("C2", "C", "Device:C", "100n", C0402, "VDDIO", Voltage="16V"),
             P("C3", "C", "Device:C", "100n", C0402, "REGOUT (datasheet)", Voltage="16V"),
             P("C4", "C", "Device:C", "2.2u", C0402, "Branch bulk", Voltage="10V")]
    nets = [("VDD", ["FB.2", "U.VDD", "U.VDDIO", "C1.1", "C2.1", "C4.1"], {"net_class": "analog"}),
            ("REGOUT", ["U.REGOUT", "C3.1"], {})]
    ports = {"VDD": Port(["FB.1"], "power_in", desc="3.3 V"),
             "GND": Port(["U.GND", "U.FSYNC", "C1.2", "C2.2", "C3.2", "C4.2"], "ground", default_net="GND"),
             "SCK": Port(["U.SCL/SPC"], net_attrs={"net_class": "high_speed"}),
             "MOSI": Port(["U.SDA/SDI"], net_attrs={"net_class": "high_speed"}),
             "MISO": Port(["U.SAO/SD0"], net_attrs={"net_class": "high_speed"}),
             "CS": Port(["U.CS"]), "INT": Port(["U.INT"], required=False)}
    return BlockBuild(parts, nets, ports, nc=["U.RESV"],
                      confirm=["ICM-20602 RESV pins: confirm in the datasheet whether any must go to GND or VDDIO."],
                      layout="Board centre, away from the buck inductor, motor/ESC wiring and board edges.")


@block("bmp280_i2c", "Barometer on I2C (Bosch BMP280)", "sensor",
       {"address": {"default": "0x76", "desc": "I2C address: 0x76 (SDO→GND) or 0x77 (SDO→VDD)"},
        "pullups": {"default": True, "desc": "Fit 4.7 kΩ I2C pull-ups here (only one set per bus)"}},
       "CSB tied high for I2C mode, 100 nF decoupling, optional pull-ups.")
def _baro(address="0x76", pullups=True):
    parts = [P("U", "U", "Sensor_Pressure:BMP280", "BMP280", "", f"Barometer (I2C {address})"),
             P("C", "C", "Device:C", "100n", C0402, "Decoupling", Voltage="16V")]
    vdd = ["U.VDD", "U.VDDIO", "U.CSB", "C.1"]
    gnd = ["U.GND", "C.2"]
    (gnd if str(address).lower() == "0x76" else vdd).append("U.SDO")
    scl, sda = ["U.SCK"], ["U.SDI"]
    if pullups:
        parts += [P("RSCL", "R", "Device:R", "4.7k", R0402, "I2C SCL pull-up"),
                  P("RSDA", "R", "Device:R", "4.7k", R0402, "I2C SDA pull-up")]
        vdd += ["RSCL.1", "RSDA.1"]
        scl.append("RSCL.2")
        sda.append("RSDA.2")
    ports = {"VDD": Port(vdd, "power_in"), "GND": Port(gnd, "ground", default_net="GND"),
             "SCL": Port(scl), "SDA": Port(sda)}
    return BlockBuild(parts, [], ports, layout="Away from the buck and heat sources; keep the vent hole unobstructed.")


@block("w25q_flash_spi", "SPI NOR flash 128 Mbit (Winbond W25Q128JV)", "memory", {},
       "100 nF decoupling, CS pull-up (deselected during boot), IO2/IO3 tied high for standard SPI.")
def _flash():
    parts = [P("U", "U", "Memory_Flash:W25Q128JVS", "W25Q128JV", "", "SPI flash"),
             P("C", "C", "Device:C", "100n", C0402, "Decoupling", Voltage="16V"),
             P("R", "R", "Device:R", "10k", R0402, "CS pull-up")]
    ports = {"VCC": Port(["U.VCC", "U.IO2", "U.IO3", "C.1", "R.1"], "power_in"),
             "GND": Port(["U.GND", "C.2"], "ground", default_net="GND"),
             "SCK": Port(["U.CLK"]), "MOSI": Port(["U.DI(IO0)"]), "MISO": Port(["U.DO(IO1)"]), "CS": Port(["U.CS", "R.2"])}
    return BlockBuild(parts, [], ports)


# =============================================================================== interfaces
@block("usb_c_device", "USB-C device port (USB 2.0) with ESD protection", "interface",
       {"vbus_diode": {"default": True, "desc": "Schottky from VBUS to the output rail (OR-ing with another supply)"}},
       "5.1 kΩ CC pull-downs (sink), USBLC6-2SC6 ESD array, optional SS34 OR-ing diode.")
def _usbc(vbus_diode=True):
    parts = [P("J", "J", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C",
               "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal", "USB-C receptacle"),
             P("RCC1", "R", "Device:R", "5.1k", R0402, "CC1 pull-down (device)"),
             P("RCC2", "R", "Device:R", "5.1k", R0402, "CC2 pull-down (device)"),
             P("ESD", "U", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "", "USB ESD protection")]
    nets = [("CC1", ["J.CC1", "RCC1.1"], {}), ("CC2", ["J.CC2", "RCC2.1"], {}),
            ("CONN_DP", ["J.D+", "ESD.1"], {"net_class": "diff_pair", "impedance_ohm": 90}),
            ("CONN_DM", ["J.D-", "ESD.3"], {"net_class": "diff_pair", "impedance_ohm": 90})]
    ports = {"DP": Port(["ESD.6"], "diff_pair", net_attrs={"net_class": "diff_pair", "impedance_ohm": 90}),
             "DM": Port(["ESD.4"], "diff_pair", net_attrs={"net_class": "diff_pair", "impedance_ohm": 90}),
             "GND": Port(["J.GND", "J.SHIELD", "RCC1.2", "RCC2.2", "ESD.GND"], "ground", default_net="GND")}
    if vbus_diode:
        parts.append(P("D", "D", "Diode:SS34", "SS34", "Diode_SMD:D_SMA", "VBUS OR-ing diode (40 V 3 A)", Voltage="40V"))
        nets.append(("VBUS", ["J.VBUS", "ESD.VBUS", "D.A"], {"net_class": "power", "voltage_v": 5.25}))
        ports["VOUT"] = Port(["D.K"], "power_out", desc="VBUS after the OR-ing diode", net_attrs={"net_class": "power"})
    else:
        ports["VBUS"] = Port(["J.VBUS", "ESD.VBUS"], "power_out", net_attrs={"net_class": "power", "voltage_v": 5.25})
    return BlockBuild(parts, nets, ports, nc=["J.SBU1", "J.SBU2"],
                      confirm=["Route D+/D− as a 90 Ω differential pair, matched, no stubs."],
                      layout="Connector on the board edge; ESD array right behind it; CC resistors near the connector.")


@block("led_indicator", "LED with calculated series resistor", "io",
       {"v_drive": {"default": 3.3, "desc": "Drive voltage (V)"}, "color": {"default": "green", "desc": "LED colour"},
        "i_ma": {"default": 2.0, "desc": "LED current (mA)"}},
       "Active-high: IN → R → LED → GND.")
def _led(v_drive=3.3, color="green", i_ma=2.0):
    vf = {"red": 1.9, "yellow": 2.0, "orange": 2.0, "green": 2.9, "blue": 2.9, "white": 2.9}.get(str(color).lower(), 2.2)
    if v_drive <= vf:
        raise ValueError(f"{color} LED needs more than {vf} V")
    r = F.led_resistor(v_supply=v_drive, v_forward=vf, i_led_ma=i_ma)
    parts = [P("R", "R", "Device:R", si(r["resistor_ohm"]), R0402, f"LED resistor ({r['actual_current_ma']} mA)"),
             P("D", "D", "Device:LED", color, "LED_SMD:LED_0603_1608Metric", f"{color} LED")]
    return BlockBuild(parts, [("K", ["R.2", "D.A"], {})],
                      {"IN": Port(["R.1"]), "GND": Port(["D.K"], "ground", default_net="GND")},
                      calculations=[{"led_resistor": r}])


CONNECTORS = {
    "jst_sh": ("Connector_JST:JST_SH_SM{n:02d}B-SRSS-TB_1x{n:02d}-1MP_P1.00mm_Horizontal", range(2, 16)),
    "jst_gh": ("Connector_JST:JST_GH_SM{n:02d}B-GHS-TB_1x{n:02d}-1MP_P1.25mm_Horizontal", range(2, 16)),
    "header_2.54": ("Connector_PinHeader_2.54mm:PinHeader_1x{n:02d}_P2.54mm_Vertical", range(1, 41)),
    "header_1.27": ("Connector_PinHeader_1.27mm:PinHeader_1x{n:02d}_P1.27mm_Vertical", range(1, 41)),
}


@block("connector", "Wire-to-board connector (JST-SH/GH or pin header)", "interface",
       {"pins": {"default": 4, "desc": "Number of pins"},
        "family": {"default": "jst_sh", "desc": "jst_sh | jst_gh | header_2.54 | header_1.27"},
        "label": {"default": "CONN", "desc": "Value shown on the board"}},
       "Ports are the pin numbers '1'…'n'; unmapped pins get no-connect flags.")
def _conn(pins=4, family="jst_sh", label="CONN"):
    n = int(pins)
    fam = CONNECTORS.get(family)
    if not fam or n not in fam[1]:
        raise ValueError(f"family must be one of {list(CONNECTORS)} with a valid pin count")
    parts = [P("J", "J", f"Connector_Generic:Conn_01x{n:02d}", str(label), fam[0].format(n=n), f"{label} connector")]
    ports = {str(i): Port([f"J.{i}"], required=False) for i in range(1, n + 1)}
    return BlockBuild(parts, [], ports, layout="On a board edge, opening outwards.")


# =============================================================================== instantiation
def list_blocks() -> List[Dict]:
    out = []
    for b in BLOCKS.values():
        try:
            probe = b.build()
            ports = {k: {"kind": v.kind, "required": v.required and not v.default_net, "desc": v.desc,
                         **({"default_net": v.default_net} if v.default_net else {})} for k, v in probe.ports.items()}
        except Exception as e:  # noqa
            ports = {"error": str(e)}
        item = {"id": b.id, "title": b.title, "category": b.category, "summary": b.summary,
                "params": b.params, "ports": ports}
        if b.id in BLOCK_GPIO:
            item["function_ports"] = BLOCK_GPIO[b.id][0]
            item["note"] = "Also accepts any GPIO name (PA0…PC15) as a port. Unmapped GPIOs are marked no-connect."
        out.append(item)
    return out


def instantiate(plan, pins_of: Callable[[str], List[Dict]], block_id: str, instance: str, params: Optional[Dict] = None,
                connect: Optional[Dict[str, str]] = None, taken_refs: Optional[set] = None) -> Dict:
    """Add a block instance to the plan. ``connect`` maps port → net name. Returns refs, nets, calculations, problems."""
    from .plan import PinResolver, PlanBlock, PlanComponent
    if block_id not in BLOCKS:
        raise KeyError(f"Unknown block '{block_id}'. Use list_blocks.")
    bd = BLOCKS[block_id]
    params = {k: v for k, v in (params or {}).items() if v is not None}
    unknown = [k for k in params if k not in bd.params]
    if unknown:
        raise ValueError(f"Unknown parameter(s) {unknown} for {block_id}; valid: {list(bd.params)}")
    build = bd.build(**params)
    connect = {str(k): v for k, v in (connect or {}).items()}
    inst = instance.strip().upper().replace(" ", "_")
    if any(b.id == instance for b in plan.blocks) or any(c.block == instance for c in plan.components):
        raise ValueError(f"Instance '{instance}' already exists in the plan; choose another name")
    problems: List[str] = []

    # ports: fixed ones + (for MCUs) function aliases / GPIO names
    ports = dict(build.ports)
    gpio_used: Dict[str, str] = {}
    if block_id in BLOCK_GPIO:
        funcs, gpios, reserved = BLOCK_GPIO[block_id]
        for port in list(connect):
            if port in ports:
                continue
            pin = funcs.get(port.upper()) or (port.upper() if port.upper() in gpios else None)
            if pin is None:
                problems.append(f"'{port}' is not a port of {block_id}: use a function name ({', '.join(sorted(funcs)[:8])}…) "
                                "or a GPIO name like PB5")
                connect.pop(port)
                continue
            if pin in reserved and port.upper() not in ("SWDIO", "SWCLK"):
                problems.append(f"{port} → {pin} is used by the block itself (crystal/SWD); pick another pin")
                connect.pop(port)
                continue
            if pin in gpio_used and gpio_used[pin] != port:
                problems.append(f"Pin conflict: {port} and {gpio_used[pin]} both need {pin}. Use a different "
                                f"peripheral instance or a plain GPIO name for one of them.")
                connect.pop(port)
                continue
            gpio_used[pin] = port
            ports[port] = Port([f"U.{pin}"], "signal", required=False)
    else:
        for port in list(connect):
            if port not in ports:
                problems.append(f"'{port}' is not a port of {block_id}; ports: {list(ports)}")
                connect.pop(port)

    # all-or-nothing: reject the call before touching the plan if the mapping is wrong
    missing_req = [pn for pn, pt in ports.items() if pt.required and not pt.default_net and not connect.get(pn)
                   and not (pt.tie_to and (connect.get(pt.tie_to) or ports[pt.tie_to].default_net))]
    if problems or missing_req:
        msgs = problems + [f"Required port {pn} ({ports[pn].desc or ports[pn].kind}) is not connected" for pn in missing_req]
        raise ValueError("Nothing was added. Fix and call add_block again with the same instance name: " + " | ".join(msgs)
                         + f". Valid ports: {list(build.ports)}" + (" plus MCU function/GPIO names" if block_id in BLOCK_GPIO else ""))

    # components
    taken = set(taken_refs or ()) | {c.ref for c in plan.components}
    refmap = {}
    plan.blocks.append(PlanBlock(id=instance, title=f"{bd.title} [{instance}]", purpose=bd.summary,
                                 layout_notes=build.layout))
    for pt in build.parts:
        ref = plan.next_ref(pt["prefix"], taken)
        taken.add(ref)
        refmap[pt["key"]] = ref
        plan.upsert_component(PlanComponent(ref=ref, lib_id=pt["lib_id"], value=pt["value"], footprint=pt["footprint"],
                                            block=instance, role=pt["role"],
                                            fields=dict(pt["fields"], Block=block_id, BlockKey=pt["key"],
                                                        **({"BlockParams": json.dumps(params)} if pt["key"] == build.parts[0]["key"] else {}))))
    res = PinResolver(pins_of)

    def nodes(local_pins: List[str]) -> List[str]:
        out = []
        for lp in local_pins:
            key, pin = lp.split(".", 1)
            got, err = res.resolve(plan, f"{refmap[key]}.{pin}")
            if err:
                problems.append(f"internal: {err}")
            out += got
        return out

    nets_made = {}
    for local, pins, attrs in build.nets:
        name = f"{inst}_{local}"
        plan.connect(name, nodes(pins), **attrs)
        nets_made[local] = name
    port_nets = {}
    unmapped_optional = []
    for pname, port in ports.items():
        net = connect.get(pname) or port.default_net
        if not net and port.tie_to:
            net = connect.get(port.tie_to) or ports[port.tie_to].default_net
        if not net:
            if port.required:
                problems.append(f"Required port {pname} ({port.desc or port.kind}) is not connected — pass connect="
                                f"{{'{pname}': '<net>'}}")
            else:
                unmapped_optional.append(pname)
            continue
        plan.connect(net, nodes(port.pins), **port.net_attrs)
        port_nets[pname] = net
    nc = nodes(build.nc)
    for pname in unmapped_optional:
        if block_id in BLOCK_GPIO and pname not in build.ports:
            continue
        nc += nodes(ports[pname].pins)
    if block_id in BLOCK_GPIO:
        funcs, gpios, reserved = BLOCK_GPIO[block_id]
        used = set(gpio_used) | reserved
        nc += nodes([f"U.{g}" for g in gpios if g not in used])
    owner = plan.node_net()
    for n in nc:
        if n not in owner and n not in plan.no_connect:
            plan.no_connect.append(n)
    plan.decisions.append(f"[{instance}] {bd.title}: " + "; ".join(f"{k}={v}" for k, v in {**{k: v['default'] for k, v in bd.params.items()}, **params}.items()))
    return {"instance": instance, "block": block_id, "refs": refmap, "port_nets": port_nets,
            "internal_nets": list(nets_made.values()), "function_pins": {v: k for k, v in gpio_used.items()} or None,
            "calculations": build.calculations, "confirm_in_datasheet": build.confirm, "layout": build.layout,
            "problems": problems}


def connect_ports(plan, pins_of: Callable[[str], List[dict]], instance: str, connect: Dict[str, str]) -> Dict:
    """Connect more ports of a block instance that is already in the plan (e.g. MCU peripherals added later)."""
    from .plan import PinResolver
    comps = [c for c in plan.components if c.block == instance]
    if not comps:
        raise ValueError(f"No block instance '{instance}' in the plan")
    block_id = (comps[0].fields or {}).get("Block", "")
    if block_id not in BLOCKS:
        raise ValueError(f"'{instance}' was not created with add_block")
    key_ref = {(c.fields or {}).get("BlockKey"): c.ref for c in comps}
    params = {}
    for c in comps:
        if (c.fields or {}).get("BlockParams"):
            params = json.loads(c.fields["BlockParams"])
    main = next((c for c in comps if (c.fields or {}).get("BlockKey") == "U"), comps[0])
    res = PinResolver(pins_of)
    problems, done = [], {}
    build = BLOCKS[block_id].build(**params)
    used = {}
    if block_id in BLOCK_GPIO:
        funcs, gpios, reserved = BLOCK_GPIO[block_id]
        owner = plan.node_net()
    for port, net in connect.items():
        pins_local = None
        if port in build.ports:
            pins_local = build.ports[port].pins
        elif block_id in BLOCK_GPIO:
            pin = funcs.get(port.upper()) or (port.upper() if port.upper() in gpios else None)
            if pin is None:
                problems.append(f"'{port}' is not a port of {block_id}")
                continue
            if pin in reserved and port.upper() not in ("SWDIO", "SWCLK"):
                problems.append(f"{port} → {pin} is used by the block itself")
                continue
            got, _ = res.resolve(plan, f"{main.ref}.{pin}")
            cur = owner.get(got[0]) if got else None
            if cur and cur != net:
                problems.append(f"{port} → {pin} is already on net {cur}; use another peripheral instance or GPIO")
                continue
            pins_local = [f"U.{pin}"]
            used[port] = pin
        else:
            problems.append(f"'{port}' is not a port of {block_id}; ports: {list(build.ports)}")
            continue
        nodes = []
        for lp in pins_local:
            key, pin = lp.split(".", 1)
            got, err = res.resolve(plan, f"{key_ref.get(key, main.ref)}.{pin}")
            if err:
                problems.append(err)
            nodes += got
        if nodes:
            attrs = build.ports[port].net_attrs if port in build.ports else {}
            plan.connect(net, nodes, **attrs)
            done[port] = net
    return {"instance": instance, "connected": done, "function_pins": used or None, "problems": problems}
