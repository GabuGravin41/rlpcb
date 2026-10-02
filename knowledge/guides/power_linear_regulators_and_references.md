---
title: Linear Regulators and Voltage References
domain: power
tags: [ldo, dropout, psrr, stability, esr, voltage reference, noise, linear regulator]
applies_to: [power boards, analog boards, mixed-signal boards, precision instrumentation]
---

## When to use a linear regulator instead of a switcher

Linear regulators (LDOs and standard linear regs) trade efficiency for simplicity, low noise, and fast transient response. Use them when:
- The voltage drop (Vin − Vout) × Iout power dissipation is manageable (see thermal section below) — generally best when the drop is small (post-regulation from a switcher, e.g., 3.3 V → 1.8 V at modest current) or current is low.
- Noise-sensitive analog/RF supplies need low output noise and high PSRR that switchers can't match without extra filtering.
- Simplicity, low BOM cost, and low EMI matter more than efficiency (no switching, no inductor, minimal radiated noise).
- As a **post-regulator** after a switching converter, to clean up switching ripple before an ADC, VCO, or other noise-sensitive load — a common and effective pattern (switcher for bulk efficiency, LDO for final noise cleanup).

Avoid linear regulators for large voltage drops at significant current — efficiency = Vout/Vin, so a 12 V → 3.3 V LDO at 1 A wastes (12−3.3)×1 = 8.7 W as heat, usually impractical without large heatsinking.

## Dropout voltage and headroom

Dropout voltage (Vdo) is the minimum (Vin − Vout) at which the regulator still maintains regulation, at a given load current. It rises with load current (LDOs are often specified at max rated current, e.g., "300 mV dropout @ 1 A").

- Standard "LDO" parts: dropout typically 100–500 mV at rated current.
- Ultra-low-dropout devices: as low as 30–100 mV.
- Older linear regulators (e.g., 7805-style): dropout ~2 V, not a true LDO.
- Design rule: ensure Vin(min) − Vout ≥ Vdo(at your actual load current) with margin (add 200–300 mV extra) across the full input tolerance range (including ripple from an upstream converter, battery discharge sag, etc.) — running too close to dropout degrades PSRR and transient response even before full dropout occurs.
- AMS1117 (common low-cost LDO, 1 A class) has ~1.0–1.3 V dropout at full load — budget input headroom accordingly; it is not ultra-low-dropout despite being widely used as one in hobbyist designs.

## Power dissipation and thermal

P_diss = (Vin − Vout) × Iout (+ small quiescent current term, usually negligible). This must be handled by the package thermal resistance (θJA for no heatsink/minimal copper, θJC + heatsink θCA for larger packages) to keep junction temperature within rating (typically 125–150°C max, design to keep well below, e.g., <100–110°C for reliability margin).

- Compute: Tj = Ta + P_diss × θJA. If Tj exceeds a safe margin (Anthropic/industry rule of thumb: keep Tj ≤ 100–110°C in the worst-case ambient for long-term reliability, even if datasheet max is higher), you need a larger package (with exposed pad), copper pour heatsinking, or a different regulator/topology (switcher pre-regulation).
- For exposed-pad packages, thermal vias under the pad connecting to an internal/bottom copper plane are essential — see power_high_current_and_thermal.md for via sizing.
- If dissipation is unavoidable and significant (>0.5–1 W in a small package), reconsider: use a switching pre-regulator to drop most of the voltage efficiently, then a small LDO for final clean-up (see above pattern) — this is nearly always better than fighting thermal design on a lossy linear regulator.

## Stability: output capacitor ESR requirements

LDO stability depends on the internal error-amplifier compensation topology, and different LDOs need different output capacitor characteristics:

- **ESR-stable ("needs ESR") LDOs**: older/bipolar designs require the output cap ESR to fall within a specific window (often 0.1–3 Ω) to place a stabilizing zero in the loop — using a very low-ESR ceramic cap can cause oscillation. These need tantalum or Al electrolytic output caps, not ceramic, unless the datasheet explicitly says otherwise.
- **Ceramic-stable LDOs** (most modern parts, including many claiming "stable with ceramic caps"): designed for low-ESR ceramic (X7R/X5R) output caps, often specifying a minimum capacitance (e.g., 1–10 µF) with an ESR ceiling instead of a floor.
- **Always check the specific datasheet's stability region plot** (capacitance vs ESR) before choosing an output cap — this is one of the most common sources of "works on the bench sometimes, oscillates other times" failures, because ESR varies with capacitor type, temperature, and aging.
- Input capacitor: typically 1–10 µF ceramic close to the Vin pin, mainly for local decoupling/transient response rather than stability, but still required by most datasheets.
- Feedforward capacitor across the feedback divider (if the LDO has an adjustable output and external divider) can improve transient response and phase margin on some parts — follow the specific datasheet.

## PSRR (Power Supply Rejection Ratio)

PSRR measures how well the regulator attenuates input ripple/noise from reaching the output, as a function of frequency. Key facts:
- PSRR is highest at DC/low frequency (often 60–80 dB) and degrades at high frequency (often down to 10–20 dB by 1 MHz) as the regulator's control loop runs out of bandwidth.
- Low dropout headroom reduces PSRR — running an LDO near its dropout limit significantly degrades both PSRR and transient response; keep 1–2 V of headroom where PSRR matters (RF/analog supplies), not just the minimum dropout margin.
- For post-regulating a switcher's output (a very common pattern to clean switching ripple before sensitive analog/RF loads), check the LDO's PSRR specifically at the switching frequency (e.g., 500 kHz–2 MHz) — many LDOs have poor PSRR exactly in this band; some are optimized for it (check "PSRR at 1 MHz" in the datasheet, not just the headline 1 kHz or 10 kHz number).
- Output capacitor choice affects high-frequency PSRR too — additional local decoupling right at the sensitive load, downstream of the LDO, is still needed (LDO is not a substitute for local decoupling, see power_decoupling_and_pdn.md).

## Voltage references

Used for ADC/DAC reference, precision comparators, and any circuit needing an absolute, stable, low-noise voltage independent of supply.

- **Types**: bandgap references (most common, good tempco, moderate noise), buried Zener references (lowest noise and best long-term stability, higher cost, e.g., used in precision instrumentation), and shunt references (simple two-terminal, e.g., using a resistor from supply, useful when a series regulator isn't convenient).
- **Key specs to match to the application**:
  - Initial accuracy (e.g., ±0.05% to ±1%) — determines whether calibration is needed.
  - Temperature coefficient (tempco, ppm/°C) — e.g., 5–50 ppm/°C for good references; matters over the operating temperature range (compute total drift = tempco × ΔT).
  - Output noise (often specified 0.1–10 Hz peak-to-peak in µVpp, and broadband noise density in nV/√Hz) — matters directly for ADC ENOB in precision measurement.
  - Long-term drift (ppm/1000 hrs) — matters for calibration-interval decisions in metrology-grade designs.
  - Line and load regulation.
- **Decoupling**: references need a local ceramic capacitor per the datasheet (often specific value/type required for stability, similar to LDOs) placed immediately at the reference's output pin, with a short, direct Kelvin trace to the ADC's reference input to avoid IR drop and noise pickup.
- **Noise reduction layout**: keep reference traces away from switching nodes, clock lines, and digital I/O; use a local ground return; for the lowest-noise designs, add an RC or LC filter between the reference and the ADC reference pin (small series R, e.g., 10–100 Ω, plus a local cap at the ADC pin) — check the ADC's reference input current/settling requirements first, since some SAR ADCs need a very low-impedance reference path (a filter resistor here can hurt, not help — check the specific ADC's REF pin drive requirements).

## Worked example: LDO thermal and headroom check

A design needs 3.3 V at 500 mA from a 5 V rail using an LDO in a small SOT-23-5-class package (θJA ≈ 150°C/W without extra copper, dropping toward ~80–100°C/W with a generous copper pour on the PCB acting as a heatsink) at a worst-case ambient of 55°C (enclosed industrial box).

1. Dropout check: Vin − Vout = 5 − 3.3 = 1.7 V, well above a typical LDO's dropout (100–500 mV at 500 mA) — plenty of headroom, dropout is not the limiting factor here.
2. Power dissipation: P = (Vin − Vout) × Iout = 1.7 V × 0.5 A = 0.85 W.
3. Junction temperature, no extra copper: Tj = Ta + P × θJA = 55 + 0.85 × 150 ≈ 55 + 127.5 = 182.5°C — this exceeds the typical 125–150°C absolute maximum rating. Unacceptable.
4. With a generous copper pour (θJA ≈ 90°C/W): Tj = 55 + 0.85 × 90 = 55 + 76.5 = 131.5°C — still marginal against a 110–125°C reliability-margin target.
5. Conclusion: this LDO/package combination is thermally inadequate for this drop and current at this ambient. Options: (a) use a larger package with an exposed pad and thermal vias (lower θJA, e.g., 40–60°C/W), (b) reduce the voltage drop by pre-regulating with a switcher to something like 3.6–3.8 V before the LDO (drop falls to ~0.3–0.5 V, P falls to ~0.15–0.25 W), or (c) reduce current draw or add forced airflow. Option (b) — switcher pre-regulation plus LDO clean-up — is usually the best engineering tradeoff when both efficiency and low noise matter.

This example illustrates why "it's just an LDO, how hard can it be" designs frequently fail thermal review — always run the Tj calculation explicitly rather than assuming a small SOT package can dissipate an arbitrary voltage drop at real-world current.

## Common mistakes

- Choosing an output capacitor without checking the ESR stability window, causing intermittent oscillation that's hard to diagnose (often temperature- or batch-dependent because ESR varies).
- Running an LDO right at its rated dropout voltage under worst-case Vin (including upstream ripple/sag), causing loss of regulation or PSRR collapse in the field even though bench testing at nominal Vin looked fine.
- Using a linear regulator for a large voltage drop at high current without checking thermal dissipation, leading to thermal shutdown or reduced reliability.
- Assuming the LDO alone provides adequate noise filtering for a switching supply's ripple without checking PSRR at the actual switching frequency.
- Placing the voltage reference's decoupling cap far from the pin, or routing the reference trace near a noisy digital/switching net.
- Forgetting local decoupling downstream of the LDO at each individual load IC (LDO output decoupling ≠ per-IC local decoupling).
- Using a reference or LDO's adjustable feedback divider with resistor values too high (noise, bias current error) or too low (wasted power, excessive loading) — mid-range (1–100 kΩ) is typical; check the datasheet's recommended range.

## Schematic review checklist

- [ ] Dropout voltage checked against worst-case Vin(min) and actual load current, with margin (~200–300 mV beyond datasheet dropout at that current).
- [ ] Power dissipation computed (P = (Vin−Vout)×Iout) and checked against package thermal capability at worst-case ambient.
- [ ] Output capacitor ESR/type matches the specific datasheet's stability region (ESR-stable vs ceramic-stable).
- [ ] Input capacitor value/type per datasheet recommendation.
- [ ] PSRR at the relevant noise frequency (e.g., upstream switcher's fsw) checked against the sensitive load's noise budget.
- [ ] Voltage reference tempco, noise, and accuracy specs matched to the application's precision requirement (not over- or under-specified).
- [ ] Reference decoupling and filter (if used) follow the datasheet, with ADC reference-pin drive requirements checked before adding series filter resistance.

## Layout review checklist

- [ ] Output/input capacitors placed immediately at the regulator's pins with short, direct traces.
- [ ] Thermal via array and copper pour present under exposed-pad packages per datasheet guidance.
- [ ] Reference and LDO feedback traces routed away from switching nodes, clocks, and digital I/O.
- [ ] Feedback/reference sense trace is a Kelvin connection from the actual load point, not tapped from a shared noisy plane.
- [ ] Local decoupling present at each downstream load IC in addition to the regulator's own output cap.
- [ ] Ground return path for the regulator/reference is short and low-impedance, not shared with high-current digital return paths.
