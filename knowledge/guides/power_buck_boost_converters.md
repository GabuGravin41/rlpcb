---
title: Buck, Boost, Buck-Boost and Flyback Converter Design
domain: power
tags: [buck, boost, buck-boost, flyback, switching regulator, hot loop, inductor selection, compensation, snubber]
applies_to: [power boards, embedded systems, industrial power supplies]
---

## Topology selection

- **Buck (step-down)**: Vout < Vin, non-isolated. Highest efficiency, simplest, most common for point-of-load (POL) regulation (e.g., 12 V/5 V → 3.3 V/1.8 V/1.0 V rails). Example parts: LM2596, TPS5430, MP2315.
- **Boost (step-up)**: Vout > Vin, non-isolated. Used for battery-to-higher-rail (e.g., single Li-ion 3.0–4.2 V → 5 V or 12 V), LED driving, PFC front ends.
- **Buck-boost (inverting or 4-switch)**: Vout can be above or below Vin — needed when input range straddles output (e.g., 3-cell battery 9–12.6 V into a fixed 12 V rail). 4-switch (H-bridge) buck-boost is the standard non-isolated choice for this; single-inductor inverting buck-boost produces a negative output.
- **Flyback**: isolated, any Vin-to-Vout ratio, single magnetic component (transformer), works well from a few watts to ~150 W. Used whenever galvanic isolation is required (mains-connected supplies, safety isolation per IEC 62368-1, sensor/field isolation) or multiple outputs are needed from one converter.
- **Forward/push-pull/half-bridge/full-bridge**: higher power isolated topologies (>100–150 W), not covered in depth here — same hot-loop and snubber principles apply, but transformer and rectification design is more involved.

Choosing: if isolation is not required and Vout is always below or always above Vin, use buck or boost respectively. If Vin range crosses Vout, use 4-switch buck-boost. If isolation is required (mains, or safety separation between field and control circuits), use flyback (low-to-medium power) or a bridge topology (higher power).

## Buck converter: core equations

- Duty cycle (CCM, ideal): D = Vout / Vin.
- Inductor ripple current: ΔIL = (Vin − Vout) × D / (L × fsw). Target ΔIL = 20–40% of Iout(max) — lower ripple means larger, more expensive inductor and lower conduction loss variation; higher ripple means smaller inductor but more core/copper loss and higher output ripple.
- Minimum inductance for a target ripple: L = (Vin − Vout) × D / (fsw × ΔIL).
- Output capacitance (ripple-voltage driven): ΔVout ≈ ΔIL × ESR + ΔIL / (8 × fsw × Cout). At switching frequencies above a few hundred kHz with low-ESR ceramic output caps, the ESR term often dominates; compute both terms and size for the tighter one.
- Peak inductor current: Ipk = Iout(max) + ΔIL/2 — this is the number to check against the inductor's saturation current rating (Isat), not just Iout(max).
- Input capacitance: buck converters draw pulsed (discontinuous) current from the input, so input cap needs low ESR and adequate ripple current rating ≈ Iout × √(D×(1−D)).

## Boost converter: core equations

- Duty cycle (CCM, ideal): D = 1 − Vin/Vout.
- Inductor current is continuous and equals input current (minus ripple) — boost draws smooth current from the source but delivers pulsed current to the output, so **output capacitor ESR and ripple current rating are critical** (output cap sees the full switch-off pulsed current).
- Inductor ripple: ΔIL = Vin × D / (L × fsw); size L similarly for 20–40% ripple of average inductor current.
- Peak switch/diode current: Ipk = IL(avg) + ΔIL/2, where IL(avg) = Iout / (1 − D) — this rises sharply as D approaches 1 (Vout >> Vin), so avoid designing boost converters with very high step-up ratios (>5–6x) on a single stage; cascade or choose a different topology instead.
- Right-half-plane zero (RHPZ): boost (and buck-boost/flyback in CCM) converters have a control-to-output transfer function with a RHPZ that limits achievable loop bandwidth — crossover frequency must be set well below the RHPZ frequency (typically fc ≤ fRHPZ/5) or the loop will be unstable. This is a key reason boost converters are harder to compensate than buck.

## Inductor selection

- **Saturation current (Isat)**: choose Isat ≥ Ipk with margin (typically 20–30%) — saturating the core causes inductance to collapse and current to spike uncontrolled, which can destroy the switch.
- **RMS/heating current rating**: separate from Isat — check the thermal current rating (often defined at ΔT = 40°C rise) against actual RMS current.
- **DCR (DC resistance)**: lower DCR = higher efficiency but usually a physically larger part; balance against board space and efficiency targets.
- **Core material/shielded vs unshielded**: shielded (closed-structure) inductors radiate less EMI and are preferred near sensitive analog circuitry or where fields must not couple into adjacent traces; unshielded (open, e.g., toroidal-looking drum-core) are cheaper but radiate more — keep them away from sensitive nets and shield-critical zones.
- Verify inductance vs DC bias curve (most manufacturers publish this) — nominal inductance can drop 20–30%+ at rated current, which affects ripple and RHPZ calculations if you used the nominal (0 A) value.

## Output/input capacitor selection

- Prefer low-ESR ceramic (X7R) for switching-frequency ripple filtering; add bulk polymer/electrolytic capacitance for load-transient response and stability where the control loop was compensated assuming some ESR (some COT/hysteretic converters need a minimum ESR — check datasheet).
- Voltage derate ceramics ≥2x working voltage (DC-bias capacitance loss, see power_decoupling_and_pdn.md).
- Ripple current rating on bulk caps must exceed the RMS ripple current calculated above — undersizing causes self-heating and shortened life.
- For boost/flyback output caps, ripple current is higher (pulsed delivery) — this is often the limiting factor in bulk cap selection, more than capacitance value.

## Feedback divider and compensation basics

- Feedback divider: Vout = Vref × (1 + R1/R2), where R1 is the top resistor (Vout to FB node) and R2 is the bottom resistor (FB node to ground). Choose R2 in the 1–10 kΩ range typically (low enough that FB pin bias current error is negligible, high enough to avoid wasting power) — check the IC's FB bias current spec; error contribution = Ibias × R1||R2, keep this << 1% of Vref.
- Add a small feedforward capacitor across R1 in some designs to improve transient response/phase margin — check the specific IC's application note before adding, as some internally compensated parts do not need or want it.
- For internally compensated converters (most integrated buck ICs like TPS5430, LM2596 in fixed configurations), follow the datasheet's recommended Cout range and ESR window exactly — deviating (e.g., using ultra-low-ESR ceramic where the IC was designed for electrolytic) can cause instability (oscillation, poor transient response) even though DC operation looks fine.
- For externally compensated converters (voltage-mode or current-mode with accessible COMP pin), the standard approach is Type II or Type III compensation:
  - Type II (one zero, one pole beyond origin) suits current-mode control with a single dominant LC or RC pole.
  - Type III (two zeros, two poles) suits voltage-mode control compensating the LC double pole of a buck's output filter.
  - Set crossover frequency fc typically at fsw/10 to fsw/5, place the compensation zero near the power-stage pole, and the compensation pole near the ESR zero or at half the switching frequency to attenuate switching noise. Detailed design normally follows the specific controller's application note (e.g., TI SLVA301, SLUA381) rather than a generic formula, because loop shaping depends on control mode (voltage/current/peak-current/COT).
- Always verify loop stability empirically if possible (bode plot via network analyzer, or at minimum a load-transient step test on the bench) rather than trusting calculation alone — component tolerances and PCB parasitics shift the real crossover and phase margin.

## The hot loop

The "hot loop" (or "power loop") is the current path that carries the switched (high di/dt) current: input capacitor → high-side switch → inductor node → (low-side switch/diode) → back to input capacitor ground. This loop must be as small as physically possible because its di/dt during switch transitions (tens to hundreds of ns) induces ringing, EMI, and voltage spikes proportional to loop inductance (V = L×di/dt).

Hot loop layout rules:
- Place input capacitor(s) immediately adjacent to the switch IC's Vin and PGND pins — within 2–3 mm, same layer if possible, with the shortest possible trace.
- Keep the hot loop entirely on one or two adjacent layers with minimal via count in the loop path itself — every via adds inductance exactly where you're trying to remove it.
- Route the loop as a tight, small physical loop, not spread across the board — smaller enclosed area = lower loop inductance = less ringing and EMI.
- For a buck: the critical hot loop is Cin(+) → high-side FET drain-source → inductor node → low-side FET/diode → Cin(−)/PGND, back to Cin. The inductor itself and the output cap are NOT part of the hot loop (output current is continuous/filtered) — don't waste hot-loop effort there.
- For a boost: the critical hot loop is the switch node → low-side switch → PGND → back through Cout — because the output diode/switch and Cout see the pulsed current here.
- Place the switch node (SW pin) copper as small as practically possible — it's a fast-slewing high-dv/dt node and a significant radiator if made into a large copper area; conversely don't make it so small/thin that it can't handle the RMS current or adds resistance.
- Keep gate drive traces (for external FET designs) short and direct, with a solid return path immediately beneath/beside them, to avoid ringing on the gate that causes shoot-through or EMI.

## Snubbers

Ringing at the switch node (from inductor + parasitic capacitance resonance, especially visible on the diode/low-side FET during turn-off) can exceed voltage ratings and generate EMI. An RC snubber across the switch node (or across a diode) damps this:

- Start from measuring the ringing frequency on the bench (or estimate from parasitic L and C).
- Snubber R ≈ the characteristic impedance of the ringing (Z = √(L/C) estimated, or found empirically by adding R alone across the node and adjusting until ringing damps without excess loss).
- Snubber C ≈ 1–3x the parasitic capacitance causing the ring (start small, e.g., 100–470 pF, and iterate).
- Snubbers dissipate power (P = C × V² × fsw for the capacitive term plus resistor loss) — they trade EMI/ringing for efficiency loss, so add only enough to meet EMI/voltage-margin requirements, verified on the bench with a scope, not by blind calculation alone.
- For flyback designs, an RCD (resistor-capacitor-diode) snubber across the primary switch is standard practice to clamp the leakage-inductance voltage spike at turn-off — size the clamp voltage comfortably below the switch's Vds rating (typically clamp level = 1.3–1.5x reflected output voltage, leaving margin to the FET's breakdown voltage) per the topology's app note (e.g., TI SLUA618, Fairchild/onsemi flyback design notes).

## Layout summary (beyond hot loop)

- Route the feedback (FB) trace as a short, direct Kelvin connection from the output capacitor (not from a random point on a wide output plane) to the FB pin, away from the switch node and inductor to avoid noise injection — a noisy FB trace causes output ripple and jitter.
- Keep the FB divider resistors close to the FB pin, not close to the output rail far away.
- Place compensation components (if external) close to the COMP pin with short traces.
- Provide a solid ground/power plane under the converter for thermal spreading and low-inductance return, but keep the switch-node copper isolated from broad ground pours (it's a noise source) — use a "cutout" or keep the plane edge back from the switch-node polygon, or place switch node on an inner layer with limited exposure.
- Thermal: for integrated converters, follow the datasheet's recommended copper area and thermal-via count under the exposed pad (typically 4–9 vias, 0.3 mm drill, in the thermal pad, connected to an internal/bottom copper plane) — see power_high_current_and_thermal.md for detailed thermal-via sizing.

## Worked example: buck converter component sizing

Design a buck converter: Vin = 12 V (±10%), Vout = 5 V, Iout(max) = 3 A, fsw = 500 kHz, target ripple ΔIL = 30% of Iout.

1. Duty cycle: D = Vout/Vin = 5/12 ≈ 0.417 (at nominal Vin; recompute at Vin_min = 10.8 V → D ≈ 0.463, and Vin_max = 13.2 V → D ≈ 0.379, since duty cycle range matters for control-loop and component stress checks).
2. Target ripple current: ΔIL = 0.30 × 3 A = 0.9 A.
3. Inductance: L = (Vin − Vout) × D / (fsw × ΔIL) = (12 − 5) × 0.417 / (500,000 × 0.9) ≈ 6.5 µH. Round to a standard value, e.g., 6.8 µH or 4.7 µH depending on availability and re-checking ripple with the actual chosen value.
4. Peak inductor current: Ipk = Iout + ΔIL/2 = 3 + 0.45 = 3.45 A. Choose an inductor with Isat ≥ 3.45 A × 1.25 (25% margin) ≈ 4.3 A, and check its RMS/thermal current rating separately against the 3 A continuous load.
5. Output ripple voltage: with a low-ESR ceramic output cap (say ESR ≈ 5 mΩ) and Cout = 22 µF: ΔVout ≈ ΔIL × ESR + ΔIL/(8×fsw×Cout) = 0.9×0.005 + 0.9/(8×500,000×22e-6) ≈ 4.5 mV + 10.2 mV ≈ 14.7 mV, about 0.3% of Vout — acceptable for most digital/general-purpose loads; tighten Cout or add more parallel caps if a tighter ripple budget (e.g., for an analog post-regulator input) is required.
6. Input capacitor RMS ripple current: Iin_rms ≈ Iout × √(D×(1−D)) ≈ 3 × √(0.417×0.583) ≈ 3 × 0.494 ≈ 1.48 A — choose input bulk/ceramic capacitance with ripple current rating comfortably above this value.
7. Verify against the hot loop: place Cin within 2–3 mm of the switch IC's Vin/PGND pins, keep the switch-node copper compact, and route feedback from the output capacitor directly to FB with a short trace away from the inductor and switch node.

This kind of explicit calculation — not just copying a reference design's BOM — is what lets you correctly re-scale a converter design for a different current, voltage, or frequency target.

## Common mistakes

- Placing the input capacitor far from the switch IC, creating a large hot loop and ringing/EMI.
- Choosing inductor saturation current based on average output current instead of peak current (Ipk = Iout + ΔIL/2).
- Using ultra-low-ESR ceramic output caps on a converter whose internal compensation assumed some ESR, causing instability.
- Routing the feedback trace near the switch node or through a noisy plane.
- Ignoring the RHPZ in boost/flyback loop compensation, resulting in a loop that looks stable in simulation but oscillates or has poor transient response in practice.
- Underrating output capacitor ripple current on boost/flyback designs where the output cap sees full pulsed current.
- Skipping a snubber entirely on a design that shows significant ringing/EMI test failures, rather than diagnosing and damping the actual resonance.
- Sizing a boost converter for very large step-up ratios (>5–6x) in a single stage, resulting in extreme duty cycle, high peak currents, and poor RHPZ margin.

## Schematic review checklist

- [ ] Topology matches the Vin/Vout relationship (buck for step-down only, boost for step-up only, buck-boost for straddling ranges, flyback/bridge if isolation required).
- [ ] Inductor value computed for target ripple current (20–40% of Iout), and Isat/RMS current rating checked against peak/RMS current with margin.
- [ ] Input and output capacitors sized for ripple voltage and ripple current (RMS), not just capacitance value; ESR compatible with the specific IC's stability requirements.
- [ ] Feedback divider computed correctly for Vref and target Vout; FB bias current error checked against divider impedance.
- [ ] Snubber/RCD clamp included where ringing or leakage-inductance spikes are expected (especially flyback primary switch).
- [ ] Compensation components (if externally compensated) chosen following the controller's specific application note, not a generic template.
- [ ] Loop stability margin (crossover frequency vs RHPZ, phase margin) considered explicitly for boost/flyback/buck-boost designs.

## Layout review checklist

- [ ] Hot loop (input cap–switch–inductor node–switch/diode–return) identified and minimized in physical area; input cap within 2–3 mm of switch IC pins.
- [ ] Switch node copper sized for current-carrying need only, not spread as a large plane; kept away from sensitive analog/feedback traces.
- [ ] Feedback trace routed as a short Kelvin connection from the output capacitor, away from noisy nodes.
- [ ] Thermal pad via count and copper area follow the datasheet's recommended pattern.
- [ ] Ground return path under the hot loop is solid and short, minimizing loop inductance.
- [ ] Gate drive traces (external FET designs) short, direct, with adjacent return path.
- [ ] Snubber components placed immediately adjacent to the node they damp.
- [ ] Output/input bulk and ceramic capacitors placed per the decoupling hierarchy (closest = highest frequency/smallest value) — see power_decoupling_and_pdn.md.
