---
title: Power Decoupling and PDN Design
domain: power
tags: [decoupling, pdn, bypass capacitors, plane capacitance, via inductance, bga, ferrite beads, impedance]
applies_to: [digital boards, mixed-signal boards, power boards, any board with switching ICs]
---

## Why decoupling exists

Every IC pulls transient current from its supply pins as internal gates switch. The power delivery network (PDN) — regulator, bulk caps, planes, local caps, vias, package — must supply that transient current while keeping the voltage at the die within its tolerance band. If it cannot, you get logic glitches, ADC code jitter, EMI, or brownout resets. Decoupling is not "add a 100 nF near every pin because everyone does it" — it is meeting a target impedance across a frequency range.

## PDN target impedance

The standard method (used across the industry, popularized by Dr. Howard Johnson and Istvan Novak):

Z_target = ΔV / ΔI

- ΔV = allowed supply ripple, typically 3–5% of Vdd for digital cores, tighter (0.5–1%) for sensitive analog/RF supplies.
- ΔI = worst-case step in current draw (not average current) — e.g., a CPU core waking all execution units, or an FPGA fabric toggling.

Example: 1.0 V core rail, 5% ripple budget = 50 mV, transient step of 5 A → Z_target = 0.05/5 = 10 mΩ. That number must hold from DC up to the frequency where the current step's rise time stops mattering (roughly f_knee = 0.35/t_rise).

The PDN impedance curve vs frequency is shaped by different elements dominating different bands:
- DC–~10 kHz: voltage regulator's control loop and bulk capacitance.
- ~10 kHz–~1 MHz: bulk/mid-value electrolytic or polymer capacitors, plus board plane resistance.
- ~1 MHz–~50 MHz: ceramic decoupling capacitors (local, X7R/X5R), their ESL and mounting inductance.
- >50 MHz: plane capacitance (the parallel-plate capacitance between adjacent power/ground planes) and package/die capacitance.

Each capacitor is only effective near its self-resonant frequency (SRF), where Z is minimum: below SRF it's capacitive, above it's inductive (ESL dominated). Use several capacitor values in parallel so their combined impedance stays below target across the whole band — this is why you see 10 µF, 1 µF, 100 nF, 10 nF stacks near high-speed ICs, not just "one big cap."

## Bulk vs local (mid) vs high-frequency decoupling

- **Bulk (10–1000 µF, electrolytic/polymer/tantalum)**: sits near the regulator output or at power entry to a sub-board region. Supplies energy for slower transients (µs–ms) and stabilizes the regulator's output during load steps. Tantalum and polymer have much lower ESR than standard Al electrolytic — prefer polymer (POSCAP, OS-CON) for low-ESR bulk in the 1–100 µF range; standard Al electrolytic ESR (0.1–1 Ω) is often too high for fast transients.
- **Mid/local (1–10 µF ceramic, X5R/X7R)**: placed within 5–10 mm of each IC's power pin cluster or power domain. Covers the 100 kHz–5 MHz band.
- **High-frequency local (10–100 nF, X7R/C0G)**: one per power pin (or per pin pair for BGA), placed as close as physically possible — ideally under or immediately adjacent to the package, on the same layer if possible or one via away.

Rule of thumb value spread: decade-spaced values (e.g., 10 µF / 1 µF / 0.1 µF / 0.01 µF) give a broader flat impedance region than many capacitors of the same value, because each value's SRF and impedance dip cover a different band. Avoid using 10+ identical 100 nF caps and calling it done — check the impedance curve (manufacturers publish S-parameter/impedance models, e.g., Murata SimSurfing, TDK, KEMET KSIM) if the design is impedance-critical.

## Capacitor selection rules

- **Dielectric**: use X7R or X5R for anything carrying real decoupling current; avoid Y5V/Z5U (huge capacitance loss vs temperature and DC bias, sometimes >80%). For precision analog references or filters needing stable capacitance, use C0G/NP0 (only available in small values, <100 nF typically).
- **Voltage derating**: ceramic capacitors lose significant capacitance under DC bias — a 16 V-rated 10 µF X5R at 5 V DC bias can lose 40–60% of nominal capacitance. Derate: choose a voltage rating at least 2x the rail voltage for small-case X7R/X5R MLCCs, and check the manufacturer's DC-bias derating curve rather than assuming datasheet capacitance holds.
- **ESR**: ceramics have very low ESR (a few mΩ to tens of mΩ) but low ESR without enough capacitance can cause control-loop instability in some LDOs designed for higher-ESR output caps (see power_linear_regulators_and_references.md) — check the regulator datasheet's stability region.
- **Package size and ESL**: smaller case size (0201, 0402) has lower mounting inductance (ESL) — mount the highest-frequency cap closest to the pin in the smallest usable case. 0402/0201 X7R has ESL roughly 0.3–0.5 nH including pads; 0805/1206 more like 0.8–1.2 nH.
- **Voltage rating for bulk electrolytic/polymer**: derate to 80% of rated voltage max continuous, and account for ripple current rating (RMS), not just DC voltage — undersized ripple current rating causes self-heating and early failure.

## Placement and via rules

- Place the smallest-value/highest-frequency capacitor closest to the IC pin. Route power in, capacitor, then via to plane — not via-then-capacitor, which adds via inductance in series before the cap can act.
- Use **two vias per capacitor pad** (one for power, one for ground) placed directly at the pad edge, not through a long thin trace. Each via adds ~0.5–1 nH of loop inductance; a short fat trace + via pair beats a long thin trace every time.
- Keep the loop area (IC pin → capacitor → return path back to IC ground) as small as physically possible. Loop inductance L ≈ 2 × ln(2h/w) type formulas aside — practically: minimize trace length, keep power and return trace tightly coupled (adjacent layers, close spacing), and place ground via right next to the power via.
- For **BGA decoupling**: place capacitors on the opposite side of the board directly under the BGA when board space allows (via-in-pad or micro-vias), or in the "capacitor ring" immediately outside the BGA footprint using the shortest escape-routing channels. High-speed BGAs (FPGAs, SoCs) often need 15–40+ decoupling caps distributed by power-pin cluster, following the vendor's power delivery guidelines (e.g., Xilinx/AMD UG583, Intel/Altera PDN guides) rather than one generic value everywhere.
- Route power and ground as **planes**, not traces, wherever current exceeds a few hundred mA or the IC is high-speed. Adjacent power/ground plane pairs with thin dielectric (e.g., 3–5 mil prepreg) give meaningful plane capacitance (tens of pF per square inch typical) that helps only above ~100 MHz — it is not a substitute for local ceramic caps at lower frequencies.

## Plane capacitance and stackup interaction

Two adjacent, fully overlapping power/ground planes act as a distributed capacitor: C_plane (pF) ≈ 0.0085 × εr × Area(in²) / thickness(mil) (parallel plate approximation, εr≈4.3 for FR4). This capacitance has extremely low inductance (distributed, not lumped) and dominates PDN impedance above ~200 MHz where discrete capacitors are already inductive. Design implication: place a solid ground plane immediately adjacent to each power plane/pour in the stackup (not separated by another signal layer) wherever high-speed digital or RF ICs are present.

## Via inductance and stitching

- A typical through-hole via (0.2–0.3 mm drill, 1.6 mm board) has ~0.5–1.2 nH self-inductance for a single via; two vias in parallel roughly halve it (mutual coupling reduces the ideal 2x, closer to 1.5–1.8x improvement).
- For power pins carrying significant transient current, use multiple vias in parallel per pad (2–4) to cut effective inductance and share current for thermal/reliability reasons.
- Stitch ground planes across layers liberally (every 5–10 mm along board edges, around connectors, and around any plane split) to keep return current paths short and low-inductance — see protection_emc_esd.md for stitching-via EMC rules.

## Ferrite bead pitfalls

Ferrite beads are used to isolate noisy digital rails from sensitive analog rails (e.g., AVDD from DVDD) by presenting high impedance at RF frequencies while passing DC. Common mistakes:

- **Beads are not fuses and not current-limiters at DC** — always check the manufacturer's DC current derating curve; impedance and saturation current drop significantly as DC bias current rises (a bead rated 600 Ω @ 100 MHz can drop by 50%+ impedance at 70% of its rated current).
- **Bead + downstream decoupling cap forms an LC resonant tank.** If lightly damped, this can produce a peaking (Q) in impedance at the resonant frequency, actually worsening noise at that frequency instead of filtering it. Add a small series resistor (1–10 Ω) or choose a bead with high internal resistance (lossy ferrite material) to damp the resonance, or verify with the bead+cap impedance vs frequency plot.
- **Do not use a ferrite bead as the primary decoupling element.** It filters noise from one rail to another; it does not supply transient current — the local decoupling capacitors on each side still need to meet their own PDN target impedance independently.
- Beads add DC resistance (tens to hundreds of mΩ) — check IR drop budget on rails with beads in series, especially at higher currents.
- Prefer beads specified for "power line filtering" impedance curves (not signal-line beads) and verify impedance at your actual noise frequency, not just the headline "@100MHz" spec.

## Worked example: sizing decoupling for a digital load step

A microcontroller/FPGA core rail is 1.0 V, allowed ripple budget is 3% (30 mV), and the fabric can step from idle to full load drawing 4 A in about 2 ns (fast digital switching edge).

1. Compute target impedance: Z_target = ΔV/ΔI = 0.030 V / 4 A = 7.5 mΩ.
2. Compute the knee frequency: f_knee = 0.35 / t_rise = 0.35 / 2 ns ≈ 175 MHz. Above this frequency the PDN doesn't need to respond faster — the current step itself isn't faster than this.
3. Below ~1 MHz: bulk capacitance and the regulator's own loop handle it — verify the regulator's transient response settles within the ripple budget for a 4 A step (check the datasheet's load-transient plot).
4. 1 MHz–50 MHz band: choose ceramic caps whose combined impedance (parallel combination, accounting for ESL and mounting inductance) stays below 7.5 mΩ across this band. A single 10 µF X5R 0402 might have SRF around 2–4 MHz; parallel several (e.g., 4–8 of them) to push the effective ESL down and broaden the low-impedance region.
5. 50–175 MHz band: this is where mounting/via inductance and plane capacitance dominate — this is why BGA/QFN parts need many small (100 nF–10 nF) caps distributed directly under or adjacent to the package, each contributing a small parallel inductance, plus plane capacitance from tightly spaced power/ground layers.
6. Verify with a capacitor vendor's impedance simulation tool (Murata SimSurfing, KEMET KSIM) using your actual mounted inductance estimate (including via count), not the bare component SRF, since mounting inductance often dominates over the capacitor's own parasitic ESL at these board-level frequencies.

This kind of explicit target-impedance calculation is what separates deliberate PDN design from copying a generic decoupling footprint from a reference design without checking whether it actually meets the specific load's transient demand.

## Common mistakes

- Sizing all decoupling caps identically (e.g., all 100 nF) — misses the higher-frequency band where SRF-appropriate smaller caps or the mid-band where larger caps are needed.
- Placing bulk capacitance far from the load and expecting it to handle fast transients — bulk caps handle slow (regulator-loop-speed) transients only; local ceramics handle fast ones.
- Routing decoupling caps through a via far from the IC pin, or sharing one via for multiple caps, creating shared inductance.
- Ignoring DC-bias capacitance derating on small-case X5R/X7R parts, resulting in far less effective capacitance than assumed.
- Using a single-point ground via for a multi-pin IC's decoupling network, creating a bottleneck and ground bounce.
- Forgetting per-pin decoupling on multi-supply-pin ICs (large FPGAs, SoCs, high-pin-count MCUs) — every VDD/VDDIO pin cluster needs its own local cap, not one shared cap for the whole package.
- Not checking capacitor ripple current rating on bulk caps used at switching frequency near a converter output.

## Schematic review checklist

- [ ] Every IC power pin has an explicit local decoupling cap shown near it in the schematic, with value chosen (not just "0.1 µF" copy-pasted everywhere without justification for high-speed/high-current ICs).
- [ ] Bulk capacitance sized and placed at each regulator output / power entry point, ESR appropriate for stability and ripple current rating adequate.
- [ ] Capacitor voltage ratings derated ≥2x rail voltage for ceramics; DC-bias capacitance loss checked for critical values.
- [ ] Dielectric chosen (X7R/X5R for power, C0G/NP0 only where precision needed) — no Y5V/Z5U on power rails.
- [ ] Ferrite bead (if used) impedance and DC current rating checked against actual noise frequency and rail current; resonance with downstream cap considered.
- [ ] Multiple decade-spaced capacitor values present on any high-speed IC or FPGA/SoC power domain, not a single repeated value.
- [ ] PDN target impedance computed (Z = ΔV/ΔI) for any rail feeding a fast-switching digital load, with capacitor selection justified against it.

## Layout review checklist

- [ ] Highest-frequency (smallest value) capacitor placed closest to the IC pin, largest bulk cap farthest.
- [ ] Two vias per decoupling cap (power + ground), placed at the pad, not via-then-cap.
- [ ] Loop area from IC pin through cap and back to ground minimized — short, fat traces, tightly coupled power/return.
- [ ] Ground plane directly adjacent to power plane/pour in stackup wherever high-speed or RF ICs exist.
- [ ] BGA/fine-pitch IC decoupling follows vendor power-delivery layout guidelines (cap count, placement zones, via-in-pad if specified).
- [ ] Multiple vias in parallel on power pins/pads carrying significant transient or DC current.
- [ ] Ground stitching vias present around plane splits, connectors, and board edges.
- [ ] No decoupling cap routed through a long thin trace or shared via with another component.
- [ ] Ferrite bead placement keeps the LC tank (bead + downstream cap) physically compact and, where required, a damping resistor included.
