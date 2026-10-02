"""Engineering calculators for PCB design.

Every function returns a dict with inputs echoed, results, the formula/standard
used and caveats — so the copilot can show its work instead of asserting numbers.
Units: mm, A, V, Ω, °C, Hz, F, H unless a parameter name says otherwise.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

OZ_TO_MM = 0.0347  # 1 oz/ft² copper ≈ 34.7 µm (35 µm commonly)
RHO_CU = 1.724e-8  # Ω·m at 20 °C
ALPHA_CU = 0.00393
C0 = 299_792_458.0

E_SERIES = {
    "E6": [1.0, 1.5, 2.2, 3.3, 4.7, 6.8],
    "E12": [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2],
    "E24": [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1],
    "E48": None, "E96": None,
}


def _eseries(name: str) -> List[float]:
    if E_SERIES.get(name):
        return E_SERIES[name]
    n = int(name[1:])
    return [round(10 ** (i / n), 2 if n <= 48 else 2) for i in range(n)]


def _fmt_si(v: float, unit: str = "") -> str:
    if v == 0:
        return f"0 {unit}".strip()
    prefixes = [(1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p")]
    for f, p in prefixes:
        if abs(v) >= f:
            return f"{v / f:.4g} {p}{unit}".strip()
    return f"{v:.3g} {unit}"


# ------------------------------------------------------------------ conductors
def trace_width(current_a: float, temp_rise_c: float = 10.0, copper_oz: float = 1.0, layer: str = "external",
                length_mm: float = 0.0, ambient_c: float = 25.0) -> Dict:
    """Minimum trace width for a current (IPC-2221B curve fit) + resistance / voltage drop."""
    k = 0.048 if layer == "external" else 0.024
    thick_mil = copper_oz * 1.378
    area_mil2 = (current_a / (k * temp_rise_c ** 0.44)) ** (1 / 0.725)
    width_mil = area_mil2 / thick_mil
    width_mm = width_mil * 0.0254
    res = {"inputs": dict(current_a=current_a, temp_rise_c=temp_rise_c, copper_oz=copper_oz, layer=layer),
           "min_width_mm": round(width_mm, 3), "min_width_mil": round(width_mil, 1),
           "cross_section_mil2": round(area_mil2, 1),
           "method": "IPC-2221B: I = k·ΔT^0.44·A^0.725 (k=0.048 external, 0.024 internal; A in mil²)",
           "caveats": ["IPC-2221 is conservative for internal layers and ignores nearby planes; IPC-2152 charts usually allow "
                       "narrower internal traces when planes are present.",
                       "Add margin for vias/necks: every via and pad neck must carry the same current.",
                       "Valid roughly for 0–35 A, ΔT 10–100 °C, widths up to ~10 mm."]}
    if length_mm:
        res.update(trace_resistance(width_mm, length_mm, copper_oz, ambient_c + temp_rise_c, current_a))
    return res


def trace_resistance(width_mm: float, length_mm: float, copper_oz: float = 1.0, temp_c: float = 25.0,
                     current_a: float = 0.0) -> Dict:
    t = copper_oz * 0.035e-3
    rho = RHO_CU * (1 + ALPHA_CU * (temp_c - 20))
    r = rho * (length_mm * 1e-3) / (width_mm * 1e-3 * t)
    d = {"resistance_ohm": round(r, 6), "resistance_mohm": round(r * 1e3, 3)}
    if current_a:
        d["voltage_drop_v"] = round(r * current_a, 5)
        d["power_loss_w"] = round(r * current_a ** 2, 5)
    return d


def via(drill_mm: float = 0.3, plating_um: float = 25.0, board_mm: float = 1.6, current_a: float = 0.0,
        temp_rise_c: float = 10.0) -> Dict:
    """Via barrel resistance, inductance, approximate current capacity (barrel treated as an internal conductor)."""
    d_out = drill_mm * 1e-3
    t = plating_um * 1e-6
    area = math.pi * ((d_out / 2) ** 2 - (d_out / 2 - t) ** 2)
    r = RHO_CU * board_mm * 1e-3 / area
    h = board_mm / 25.4 * 1000  # mils? inductance formula uses inches
    h_in, d_in = board_mm / 25.4, drill_mm / 25.4
    l_nh = 5.08 * h_in * (math.log(4 * h_in / d_in) + 1)
    area_mil2 = area / (0.0254e-3) ** 2
    i_max = 0.048 * temp_rise_c ** 0.44 * area_mil2 ** 0.725  # barrel is thermally well coupled: external k
    out = {"inputs": dict(drill_mm=drill_mm, plating_um=plating_um, board_mm=board_mm),
           "resistance_mohm": round(r * 1e3, 3), "inductance_nh": round(l_nh, 3),
           "approx_current_a": round(i_max, 2),
           "method": "R=ρL/A (barrel annulus); L≈5.08h[ln(4h/d)+1] nH (h,d in inches); current via IPC-2221 fit on barrel area",
           "caveats": ["Current rating is approximate; use ≥2 vias per amp-level connection and more for thermal paths."]}
    if current_a:
        out["vias_needed"] = max(1, math.ceil(current_a / max(i_max, 1e-9)))
    return out


# ------------------------------------------------------------------ impedance
def microstrip(width_mm: float, height_mm: float, er: float = 4.3, thickness_mm: float = 0.035) -> Dict:
    """Surface microstrip Z0 (Hammerstad–Jensen with thickness correction)."""
    w, h, t = width_mm, height_mm, thickness_mm
    if t > 0:
        dw = (t / math.pi) * (1 + math.log(4 * math.e / math.sqrt((t / h) ** 2 + (1 / math.pi / (w / t + 1.1)) ** 2)))
        dwr = 0.5 * (1 + 1 / math.cosh(math.sqrt(er - 1))) * dw
    else:
        dw = dwr = 0
    def z0_air(u):
        f = 6 + (2 * math.pi - 6) * math.exp(-((30.666 / u) ** 0.7528))
        return 60 * math.log(f / u + math.sqrt(1 + (2 / u) ** 2))
    def eeff(u):
        a = 1 + (1 / 49) * math.log((u ** 4 + (u / 52) ** 2) / (u ** 4 + 0.432)) + (1 / 18.7) * math.log(1 + (u / 18.1) ** 3)
        b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
        return (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / u) ** (-a * b)
    u1, ur = (w + dw) / h, (w + dwr) / h
    ee = eeff(ur) * (z0_air(u1) / z0_air(ur)) ** 2
    z = z0_air(ur) / math.sqrt(eeff(ur))
    delay = math.sqrt(ee) / C0 * 1e12 / 1e3  # ps per mm
    return {"inputs": dict(width_mm=w, height_mm=h, er=er, thickness_mm=t), "z0_ohm": round(z, 2),
            "er_effective": round(ee, 3), "delay_ps_per_mm": round(delay, 3),
            "method": "Hammerstad–Jensen microstrip with Wheeler thickness correction (±2% typ.)",
            "caveats": ["Solder mask lowers Z by ~1–3 Ω; ask the fab for their impedance calculation (they tune width)."]}


def stripline(width_mm: float, b_mm: float, er: float = 4.3, thickness_mm: float = 0.035) -> Dict:
    """Symmetric stripline Z0 (Wheeler/Cohn). b = total dielectric thickness between the two planes."""
    w, b, t = width_mm, b_mm, thickness_mm
    m = 6 / (3 + 2 * t / (b - t))
    x = t / b
    dw = (x / (math.pi * (1 - x))) * (1 - 0.5 * math.log((x / (2 - x)) ** 2 + (0.0796 * x / (w / b + 1.1 * x)) ** m))
    wp = w / (b - t) + dw
    z = 30 / math.sqrt(er) * math.log(1 + (4 / (math.pi * wp)) * ((8 / (math.pi * wp)) + math.sqrt((8 / (math.pi * wp)) ** 2 + 6.27)))
    return {"inputs": dict(width_mm=w, b_mm=b, er=er, thickness_mm=t), "z0_ohm": round(z, 2),
            "delay_ps_per_mm": round(math.sqrt(er) / C0 * 1e9, 3),
            "method": "Wheeler stripline formula with finite-thickness correction (±1–2%)"}


def differential(z0_single_ohm: float, spacing_mm: float, height_mm: float, kind: str = "microstrip") -> Dict:
    """Edge-coupled differential impedance from single-ended Z0 (IPC-2141 approximations)."""
    s, h = spacing_mm, height_mm
    if kind == "microstrip":
        zd = 2 * z0_single_ohm * (1 - 0.48 * math.exp(-0.96 * s / h))
        m = "Zdiff ≈ 2·Z0·(1 − 0.48·e^(−0.96·s/h)) (IPC-2141 edge-coupled microstrip)"
    else:
        zd = 2 * z0_single_ohm * (1 - 0.347 * math.exp(-2.9 * s / (2 * h)))
        m = "Zdiff ≈ 2·Z0·(1 − 0.347·e^(−2.9·s/b)) (IPC-2141 edge-coupled stripline, b=2h)"
    return {"inputs": dict(z0_single_ohm=z0_single_ohm, spacing_mm=s, height_mm=h, kind=kind),
            "zdiff_ohm": round(zd, 2), "method": m,
            "caveats": ["First-order approximation. Use a field solver (KiCad Calculator, Saturn PCB, fab's tool) for sign-off."]}


def solve_width_for_impedance(target_ohm: float, height_mm: float, er: float = 4.3, kind: str = "microstrip",
                              thickness_mm: float = 0.035, spacing_mm: Optional[float] = None) -> Dict:
    """Find the trace width that gives target single-ended (or differential when spacing given) impedance."""
    lo, hi = 0.02, 10.0
    def z_of(w):
        z = microstrip(w, height_mm, er, thickness_mm)["z0_ohm"] if kind == "microstrip" else stripline(w, height_mm, er, thickness_mm)["z0_ohm"]
        if spacing_mm is not None:
            h = height_mm if kind == "microstrip" else height_mm / 2
            return differential(z, spacing_mm, h, kind)["zdiff_ohm"]
        return z
    for _ in range(80):
        mid = (lo + hi) / 2
        if z_of(mid) > target_ohm:
            lo = mid
        else:
            hi = mid
    w = (lo + hi) / 2
    return {"inputs": dict(target_ohm=target_ohm, height_mm=height_mm, er=er, kind=kind, spacing_mm=spacing_mm),
            "width_mm": round(w, 4), "achieved_ohm": round(z_of(w), 2),
            "note": "Starting point only — confirm with the fab's stackup/impedance table."}


def critical_length(rise_time_ns: float, er_eff: float = 3.0) -> Dict:
    """Length above which a trace should be treated as a transmission line (≈ 1/6 of rise-time distance)."""
    v = C0 / math.sqrt(er_eff)  # m/s
    dist = v * rise_time_ns * 1e-9
    return {"inputs": dict(rise_time_ns=rise_time_ns, er_eff=er_eff), "rise_distance_mm": round(dist * 1e3, 1),
            "critical_length_mm": round(dist * 1e3 / 6, 1),
            "knee_frequency_mhz": round(0.5 / rise_time_ns * 1e3, 1),
            "method": "l_crit ≈ t_r·v/6; f_knee ≈ 0.5/t_r",
            "advice": "Traces longer than the critical length need controlled impedance and termination."}


def length_match(skew_ps: float, er_eff: float = 3.0) -> Dict:
    ps_per_mm = math.sqrt(er_eff) / C0 * 1e9
    return {"inputs": dict(skew_ps=skew_ps, er_eff=er_eff), "delay_ps_per_mm": round(ps_per_mm, 3),
            "max_length_mismatch_mm": round(skew_ps / ps_per_mm, 3)}


# ------------------------------------------------------------------ spacing
_IPC2221_TABLE = [  # (max V peak, B1 internal, B2 ext uncoated sea-level, B3 ext uncoated >3050m, B4 ext coated, A5 ext conformal assy, A6 ext uncoated assy, A7 ext coated assy)
    (15, 0.05, 0.1, 0.1, 0.05, 0.13, 0.13, 0.13),
    (30, 0.05, 0.1, 0.1, 0.05, 0.13, 0.25, 0.13),
    (50, 0.1, 0.6, 0.6, 0.13, 0.13, 0.4, 0.13),
    (100, 0.1, 0.6, 1.5, 0.13, 0.13, 0.5, 0.13),
    (150, 0.2, 0.6, 3.2, 0.4, 0.4, 0.8, 0.4),
    (170, 0.2, 1.25, 3.2, 0.4, 0.4, 0.8, 0.4),
    (250, 0.2, 1.25, 6.4, 0.4, 0.4, 0.8, 0.4),
    (300, 0.2, 1.25, 12.5, 0.4, 0.4, 0.8, 0.8),
    (500, 0.25, 2.5, 12.5, 0.8, 0.8, 1.5, 0.8),
]
_PER_V_ABOVE_500 = (0.0025, 0.005, 0.025, 0.00305, 0.00305, 0.00305, 0.00305)


def clearance(voltage_peak_v: float, condition: str = "B2") -> Dict:
    """Minimum conductor spacing per IPC-2221B Table 6-1. condition: B1..B4, A5..A7."""
    cols = ["B1", "B2", "B3", "B4", "A5", "A6", "A7"]
    i = cols.index(condition)
    v = abs(voltage_peak_v)
    if v <= 500:
        for row in _IPC2221_TABLE:
            if v <= row[0]:
                mm = row[i + 1]
                break
    else:
        mm = _IPC2221_TABLE[-1][i + 1] + (v - 500) * _PER_V_ABOVE_500[i]
    desc = {"B1": "internal conductors", "B2": "external, uncoated, sea level–3050 m", "B3": "external, uncoated, >3050 m",
            "B4": "external, permanent polymer coating", "A5": "external, conformal-coated assembly",
            "A6": "external component lead/termination, uncoated", "A7": "external component lead/termination, coated"}
    return {"inputs": dict(voltage_peak_v=voltage_peak_v, condition=condition), "min_spacing_mm": round(mm, 3),
            "condition": desc[condition], "method": "IPC-2221B Table 6-1 (functional spacing)",
            "caveats": ["This is functional spacing, NOT safety creepage/clearance. Mains or user-accessible circuits must "
                        "follow the product safety standard (IEC 62368-1, IEC 61010-1, IEC 60335) which typically demands "
                        "far more (e.g. ~2.5–3 mm clearance and 2.5–6.4 mm creepage for 230 VAC basic/reinforced insulation).",
                        "Use slots in the PCB to increase creepage between primary and secondary."]}


# ------------------------------------------------------------------ passives
def nearest_e(value: float, series: str = "E24") -> Dict:
    vals = _eseries(series)
    exp = math.floor(math.log10(value))
    cands = [m * 10 ** e for e in (exp - 1, exp, exp + 1) for m in vals]
    best = min(cands, key=lambda c: abs(c - value))
    return {"value": value, "series": series, "nearest": best, "error_percent": round((best - value) / value * 100, 3)}


def divider(vout: float, vref: float = None, vin: float = None, series: str = "E96", r_total_target: float = 100e3,
            i_bias_a: float = 0.0) -> Dict:
    """Pick R1 (top) / R2 (bottom) so that Vout·R2/(R1+R2) = Vref (feedback) or Vout = Vin·R2/(R1+R2)."""
    if vref is not None:
        ratio = vref / vout  # R2/(R1+R2)
        mode = "feedback: Vout = Vref·(1 + R1/R2)"
    elif vin is not None:
        ratio = vout / vin
        mode = "divider: Vout = Vin·R2/(R1+R2)"
    else:
        raise ValueError("Give vref (feedback divider) or vin (plain divider)")
    vals = _eseries(series)
    best = None
    for e2 in range(2, 7):
        for m2 in vals:
            r2 = m2 * 10 ** e2
            r1_ideal = r2 * (1 - ratio) / ratio
            if r1_ideal <= 0:
                continue
            r1 = nearest_e(r1_ideal, series)["nearest"]
            got = r2 / (r1 + r2)
            err = abs(got - ratio) / ratio
            score = err + 0.02 * abs(math.log10((r1 + r2) / r_total_target))
            if best is None or score < best[0]:
                best = (score, r1, r2, got)
    _, r1, r2, got = best
    actual = (vref / got) if vref is not None else vin * got
    return {"inputs": dict(vout=vout, vref=vref, vin=vin, series=series), "mode": mode,
            "R1_top_ohm": r1, "R2_bottom_ohm": r2, "R1": _fmt_si(r1, "Ω"), "R2": _fmt_si(r2, "Ω"),
            "actual_output_v": round(actual, 4), "error_percent": round((actual - vout) / vout * 100, 3),
            "divider_current_ua": round(((vout if vref else vin) / (r1 + r2)) * 1e6, 2),
            "advice": "Keep divider current ≥ 100× the feedback pin bias current; place R2 and the FB node close to the IC."}


def led_resistor(v_supply: float, v_forward: float = 2.0, i_led_ma: float = 5.0, series: str = "E24") -> Dict:
    r = (v_supply - v_forward) / (i_led_ma / 1000)
    n = nearest_e(r, series)["nearest"]
    i = (v_supply - v_forward) / n
    return {"inputs": dict(v_supply=v_supply, v_forward=v_forward, i_led_ma=i_led_ma), "resistor_ohm": n,
            "actual_current_ma": round(i * 1000, 2), "resistor_power_mw": round(i * i * n * 1000, 2)}


def rc_filter(r_ohm: float = None, c_f: float = None, fc_hz: float = None) -> Dict:
    if fc_hz is None:
        fc = 1 / (2 * math.pi * r_ohm * c_f)
        return {"fc_hz": round(fc, 4), "fc": _fmt_si(fc, "Hz"), "tau_s": r_ohm * c_f}
    if r_ohm is not None:
        c = 1 / (2 * math.pi * r_ohm * fc_hz)
        return {"c_f": c, "c": _fmt_si(c, "F"), "nearest_E12": _fmt_si(nearest_e(c, "E12")["nearest"], "F")}
    r = 1 / (2 * math.pi * c_f * fc_hz)
    return {"r_ohm": r, "nearest_E24": _fmt_si(nearest_e(r, "E24")["nearest"], "Ω")}


def crystal_load_caps(cl_pf: float, c_stray_pf: float = 3.0) -> Dict:
    c = 2 * (cl_pf - c_stray_pf)
    return {"inputs": dict(cl_pf=cl_pf, c_stray_pf=c_stray_pf), "each_cap_pf": round(c, 2),
            "nearest_E12_pf": nearest_e(c, "E12")["nearest"] if c > 0 else None,
            "method": "CL = C1·C2/(C1+C2) + Cstray, C1 = C2 = 2(CL − Cstray)",
            "advice": "Cstray is usually 2–5 pF (pins + traces). Keep the crystal and caps within ~5 mm of the MCU pins, "
                      "with a ground pour underneath and no signals routed under the crystal."}


# ------------------------------------------------------------------ power
def buck(vin_min: float, vin_max: float, vout: float, iout: float, fsw_hz: float, ripple_ratio: float = 0.3,
         vout_ripple_mv: float = 20.0, efficiency: float = 0.9) -> Dict:
    """Buck converter power stage sizing (CCM)."""
    d_max = vout / (vin_min * efficiency)
    d_min = vout / vin_max
    di = ripple_ratio * iout
    L = (vin_max - vout) * d_min / (fsw_hz * di)
    ipk = iout + di / 2
    cout_min = di / (8 * fsw_hz * vout_ripple_mv * 1e-3)
    esr_max = vout_ripple_mv * 1e-3 / di
    icin_rms = iout * math.sqrt(d_max * (1 - d_max))
    cin = iout * d_max * (1 - d_max) / (fsw_hz * 0.05 * vin_min)  # 5 % input ripple target
    return {"inputs": dict(vin_min=vin_min, vin_max=vin_max, vout=vout, iout=iout, fsw_hz=fsw_hz, ripple_ratio=ripple_ratio),
            "duty_range": [round(d_min, 3), round(d_max, 3)],
            "inductor_h": L, "inductor": _fmt_si(L, "H"), "inductor_nearest_E6": _fmt_si(nearest_e(L, "E6")["nearest"], "H"),
            "inductor_ripple_a": round(di, 3), "inductor_peak_a": round(ipk, 3),
            "inductor_saturation_min_a": round(ipk * 1.3, 2),
            "cout_min_f": cout_min, "cout_min": _fmt_si(cout_min, "F"), "cout_esr_max_ohm": round(esr_max, 4),
            "cin_rms_current_a": round(icin_rms, 3), "cin_min_f": cin, "cin_min": _fmt_si(cin, "F"),
            "method": "L = (Vin_max−Vout)·D/(fsw·ΔI); Cout ≥ ΔI/(8·fsw·ΔV); Icin_rms = Iout·√(D(1−D))",
            "advice": ["Choose inductor Isat ≥ 1.3× peak and Irms ≥ Iout.",
                       "Use X5R/X7R ceramics derated for DC bias (a 10 µF 0805 at 5 V may be only ~4 µF).",
                       "Hot loop: Cin – high-side FET – low-side FET/diode must be the smallest loop on the board."]}


def boost(vin_min: float, vin_max: float, vout: float, iout: float, fsw_hz: float, ripple_ratio: float = 0.3,
          vout_ripple_mv: float = 50.0, efficiency: float = 0.88) -> Dict:
    d_max = 1 - vin_min * efficiency / vout
    iin = iout / (1 - d_max)
    di = ripple_ratio * iin
    L = vin_min * d_max / (fsw_hz * di)
    ipk = iin + di / 2
    cout = iout * d_max / (fsw_hz * vout_ripple_mv * 1e-3)
    return {"inputs": dict(vin_min=vin_min, vin_max=vin_max, vout=vout, iout=iout, fsw_hz=fsw_hz),
            "duty_max": round(d_max, 3), "input_current_a": round(iin, 3), "inductor": _fmt_si(L, "H"), "inductor_h": L,
            "inductor_peak_a": round(ipk, 3), "switch_peak_a": round(ipk, 3), "cout_min": _fmt_si(cout, "F"),
            "diode_avg_current_a": iout, "method": "D = 1 − Vin·η/Vout; L = Vin·D/(fsw·ΔI); Cout ≥ Iout·D/(fsw·ΔV)",
            "advice": ["Output capacitor carries pulsed current: the hot loop is switch – diode – Cout.",
                       "A boost cannot disconnect the load: Vin passes to Vout through the diode when off."]}


def ldo(vin: float, vout: float, iout: float, iq_a: float = 0.0, theta_ja_c_per_w: float = 60.0, ambient_c: float = 40.0,
        tj_max_c: float = 125.0) -> Dict:
    p = (vin - vout) * iout + vin * iq_a
    tj = ambient_c + p * theta_ja_c_per_w
    return {"inputs": dict(vin=vin, vout=vout, iout=iout, theta_ja=theta_ja_c_per_w, ambient_c=ambient_c),
            "dissipation_w": round(p, 3), "junction_temp_c": round(tj, 1), "ok": tj < tj_max_c - 10,
            "efficiency_percent": round(vout * iout / (vin * (iout + iq_a)) * 100, 1),
            "max_ambient_c": round(tj_max_c - p * theta_ja_c_per_w, 1),
            "advice": "If Tj is within 10 °C of the limit, add copper/thermal vias (θja depends heavily on board copper) or use a buck."}


def mosfet_loss(i_rms: float, rds_on_ohm: float, vds_v: float = 0.0, i_sw_a: float = 0.0, t_rise_ns: float = 0.0,
                t_fall_ns: float = 0.0, fsw_hz: float = 0.0, qg_nc: float = 0.0, vgs_v: float = 10.0,
                theta_ja: float = 40.0, ambient_c: float = 40.0, temp_coeff: float = 1.5) -> Dict:
    p_cond = i_rms ** 2 * rds_on_ohm * temp_coeff
    p_sw = 0.5 * vds_v * i_sw_a * (t_rise_ns + t_fall_ns) * 1e-9 * fsw_hz
    p_gate = qg_nc * 1e-9 * vgs_v * fsw_hz
    p = p_cond + p_sw
    return {"conduction_w": round(p_cond, 4), "switching_w": round(p_sw, 4), "gate_drive_w": round(p_gate, 4),
            "total_in_fet_w": round(p, 4), "junction_temp_c": round(ambient_c + p * theta_ja, 1),
            "note": f"Rds(on) multiplied by {temp_coeff} for hot-junction increase."}


def pdn_target_impedance(v_rail: float, ripple_percent: float, transient_a: float) -> Dict:
    z = v_rail * ripple_percent / 100 / transient_a
    return {"inputs": dict(v_rail=v_rail, ripple_percent=ripple_percent, transient_a=transient_a),
            "z_target_ohm": round(z, 5), "z_target_mohm": round(z * 1e3, 3),
            "method": "Ztarget = Vrail·ripple%/ΔI",
            "advice": "Keep |Z| below target from DC up to the frequency where the package/die capacitance takes over. "
                      "Mix values (e.g. 100 µF bulk, 10 µF, 1 µF, 100 nF) and minimise mounting inductance (short, wide via "
                      "connections, vias beside pads, caps on the layer nearest the plane pair)."}


def cap_resonance(c_f: float, esl_h: float = 0.5e-9, esr_ohm: float = 0.01) -> Dict:
    f = 1 / (2 * math.pi * math.sqrt(c_f * esl_h))
    return {"self_resonant_hz": f, "self_resonant": _fmt_si(f, "Hz"), "impedance_at_srf_ohm": esr_ohm,
            "note": "Above the SRF the capacitor behaves as an inductor; ESL is dominated by mounting (pads + vias)."}


def shunt(i_max_a: float, v_sense_max_mv: float = 50.0, series: str = "E24") -> Dict:
    r = v_sense_max_mv * 1e-3 / i_max_a
    rn = nearest_e(r, series)["nearest"]
    return {"shunt_ohm": rn, "shunt": _fmt_si(rn, "Ω"), "power_w": round(i_max_a ** 2 * rn, 4),
            "recommended_rating_w": round(i_max_a ** 2 * rn * 2, 3),
            "advice": "Use 4-terminal (Kelvin) connection: route sense traces from the inner edge of the shunt pads as a "
                      "differential pair to the amplifier, away from the high-current path."}


def battery_runtime(capacity_mah: float, load_ma: float, derate: float = 0.8, voltage_v: float = 0.0) -> Dict:
    h = capacity_mah * derate / load_ma
    d = {"runtime_h": round(h, 2), "runtime_days": round(h / 24, 2)}
    if voltage_v:
        d["energy_wh"] = round(capacity_mah * voltage_v / 1000, 2)
    return d


def thermal_vias(power_w: float, delta_t_c: float = 20.0, drill_mm: float = 0.3, plating_um: float = 25,
                 board_mm: float = 1.6) -> Dict:
    """Number of plated vias to conduct heat through the board (copper barrel conduction only)."""
    k_cu = 385.0
    d = drill_mm * 1e-3
    t = plating_um * 1e-6
    area = math.pi * ((d / 2) ** 2 - (d / 2 - t) ** 2)
    r_via = (board_mm * 1e-3) / (k_cu * area)  # K/W per via
    n = math.ceil(power_w * r_via / delta_t_c)
    return {"thermal_resistance_per_via_c_per_w": round(r_via, 1), "vias_needed": n,
            "array_suggestion": f"{math.ceil(math.sqrt(n))}×{math.ceil(math.sqrt(n))} grid at 1.0–1.2 mm pitch under the thermal pad",
            "caveats": ["Ignores the spreading resistance of planes and solder fill; filled/capped vias conduct better.",
                        "Tent or plug vias in the pad (or use via-in-pad) to stop solder wicking."]}


def wavelength(freq_hz: float, er_eff: float = 1.0) -> Dict:
    lam = C0 / (freq_hz * math.sqrt(er_eff))
    return {"wavelength_mm": round(lam * 1e3, 3), "quarter_wave_mm": round(lam * 250, 3),
            "lambda_over_20_mm": round(lam * 50, 3)}


CALCULATORS = {
    "trace_width": trace_width, "trace_resistance": trace_resistance, "via": via, "microstrip": microstrip,
    "stripline": stripline, "differential": differential, "solve_width_for_impedance": solve_width_for_impedance,
    "critical_length": critical_length, "length_match": length_match, "clearance": clearance,
    "nearest_e": nearest_e, "divider": divider, "led_resistor": led_resistor, "rc_filter": rc_filter,
    "crystal_load_caps": crystal_load_caps, "buck": buck, "boost": boost, "ldo": ldo, "mosfet_loss": mosfet_loss,
    "pdn_target_impedance": pdn_target_impedance, "cap_resonance": cap_resonance, "shunt": shunt,
    "battery_runtime": battery_runtime, "thermal_vias": thermal_vias, "wavelength": wavelength,
}


def describe() -> Dict[str, str]:
    import inspect
    out = {}
    for k, f in CALCULATORS.items():
        sig = str(inspect.signature(f)).replace(" -> Dict", "")
        doc = (f.__doc__ or "").strip().split("\n")[0]
        out[k] = f"{k}{sig} — {doc}"
    return out


def run(name: str, **params) -> Dict:
    if name not in CALCULATORS:
        raise KeyError(f"Unknown calculator '{name}'. Available: {', '.join(CALCULATORS)}")
    return CALCULATORS[name](**params)
