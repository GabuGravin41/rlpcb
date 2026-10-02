---
title: Protection, EMC and ESD Design
domain: mixed-signal
tags: [reverse polarity, overvoltage, tvs, esd, common-mode choke, emc, return path, stitching vias, shielding, cispr32, iec61000]
applies_to: [all boards, especially field-connected, portable, and safety-relevant designs]
---

## Reverse polarity protection

- **Series diode**: simplest method — a diode in series with the supply input blocks reverse current entirely. Downside: forward voltage drop (0.3–0.7 V for Schottky/standard diode) wastes power and headroom, scaling with load current (P = Vf × I).
- **Ideal diode / MOSFET-based protection**: a P-channel or N-channel MOSFET wired so correct polarity turns it on (near-zero Rds(on) drop) and reverse polarity leaves it off (blocking) — far more efficient than a series diode at any meaningful current, standard in modern designs. For N-channel implementations, a charge pump or dedicated ideal-diode controller IC drives the gate.
- **Crowbar/shunt protection**: a large device (SCR, TVS, or MOSFET) that intentionally shorts the input when reverse polarity or overvoltage is detected, relying on an upstream fuse to blow and disconnect — used where a hard fail-safe disconnection is preferred over graceful blocking, common on inputs from unpredictable field wiring.
- Always size the protection device (diode, MOSFET, or crowbar) for the full fault current available from the source (e.g., a vehicle battery or a bench supply with high short-circuit current capability), not just normal operating current.

## Overvoltage protection

- **Clamping (TVS, Zener)**: limits voltage excursions to a safe level by conducting current away once the threshold is exceeded — see TVS selection guidance in industrial_plc_io.md (standoff voltage, clamping voltage, peak pulse power matched to the expected transient's energy/waveform).
- **Crowbar (SCR-based)**: for higher-energy or sustained overvoltage faults where a clamp alone would overheat, an SCR crowbar shorts the rail hard once triggered (via a comparator/Zener reference), relying on upstream fusing/current limiting to then safely disconnect — common in precision analog supply protection where downstream ICs cannot tolerate even a brief overvoltage a TVS's residual clamp voltage might allow.
- **Active OVP (comparator + switch disconnect)**: a comparator monitors the rail and drives a series MOSFET off (rather than shorting) when overvoltage is detected — avoids the crowbar's reliance on a fuse blowing, useful where a clean shutdown/recovery is preferred over a destructive fuse-clearing event.
- Match protection response time to the fault's rise time: a slow comparator-based active OVP is fine for slow fault conditions (e.g., a misconfigured supply) but far too slow for a fast transient (ESD, EFT) — those need TVS/clamping devices with nanosecond-scale response.

## ESD protection at connectors

- Every externally accessible connector (USB, field I/O, any user-touchable port) needs ESD protection sized to the relevant IEC 61000-4-2 test level for the product's equipment class (commonly ±8 kV contact / ±15 kV air for products with routine human contact, lower levels may apply for enclosed industrial equipment — check the applicable product standard).
- Use dedicated low-capacitance ESD protection diode arrays on high-speed signal lines (USB, Ethernet, display interfaces) where a standard TVS's junction capacitance (tens to hundreds of pF) would degrade signal integrity — low-capacitance ESD parts are specifically designed with <1 pF typical capacitance for this purpose.
- Place ESD protection components as close to the connector as physically possible, with short, direct, low-inductance ground/return connections — the protection device's effectiveness is degraded significantly by trace/lead inductance during the fast (sub-nanosecond rise time) ESD event, since V = L×di/dt can let the protected node spike well above the device's rated clamp voltage if the connecting trace is long.
- Provide a direct, low-impedance path from the ESD protection device's ground reference to the chassis/earth ground, not routed through the sensitive signal ground plane — this keeps the ESD discharge current from flowing through (and disturbing) the sensitive circuit's own return path.

## Common-mode chokes

Common-mode chokes pass differential (signal) current unimpeded while presenting high impedance to common-mode current (current flowing the same direction on both conductors, typically noise coupled from an external source or radiated/conducted from the board itself).

- Used on cable entries (Ethernet, motor phase cables, any long external cable) to suppress common-mode noise that would otherwise radiate from the cable (the cable acts as an antenna for common-mode current) or couple external noise into the board.
- Choose the choke's impedance-vs-frequency curve to cover the actual problem frequency range (check impedance at the specific frequency of concern, not just a headline spec) and its current rating to exceed the actual differential current without core saturation (a saturated choke loses its common-mode impedance).
- On differential signal pairs (USB, Ethernet, RS-485/CAN), a common-mode choke rated for the signal's differential impedance and bandwidth must not distort the differential signal — use parts specifically qualified for that interface (e.g., USB-qualified common-mode chokes preserve USB signal integrity while filtering common-mode noise); a generic power-line choke is not appropriate here.

## EMC design rules: return paths

- Every signal's return current follows the path of least impedance, which at high frequency is the path directly beneath the signal trace on the nearest reference plane (not necessarily the shortest physical path, but the lowest-inductance one) — a solid, uninterrupted reference plane immediately beneath every signal layer is the single most effective and cheapest EMC design practice available.
- **Never route a high-speed or high-di/dt signal trace across a gap/split in its return plane** — this forces the return current to detour around the gap, creating a large loop (high radiated emission and high susceptibility to external noise) exactly at the split location. If a plane split is unavoidable (e.g., isolation boundary), route the crossing signal (if any signal must cross at all, which should be minimized) through a dedicated isolation component (transformer, isolator) at a single defined crossing point, not as a bare trace over the gap.
- When a signal must change reference planes (e.g., moving from a layer referenced to GND to one referenced to a different plane, such as through a via), provide a nearby stitching via connecting the two reference planes so the return current has a short path to follow the signal's layer transition — place the stitching via within a few mm of the signal via, ideally adjacent to it.
- Keep return planes solid under connectors and cable entry points especially — this is where external common-mode currents enter/exit and where a clean, low-impedance ground reference matters most for both emissions and immunity.

## Stitching vias

- Stitch ground planes together across all layers at regular intervals along board edges, around connectors, and around any plane split or cutout — typical spacing guidance is roughly λ/20 of the highest frequency of concern (for EMC purposes up to ~1 GHz range in many digital designs, this works out to a few mm to ~1 cm spacing; tighter spacing for higher-frequency designs).
- Stitch around the perimeter of any RF or shielded region especially densely, to maintain a continuous low-impedance ground reference around the shield's contact points.
- Stitching vias near connectors also provide a short return path for ESD/EFT energy entering through the connector's chassis-ground pins, keeping that energy from flowing through the sensitive circuit's signal-reference plane instead.

## Shielding

- **Board-level shielding cans**: metal enclosures soldered to a ground-connected perimeter pattern on the PCB, used to contain/exclude RF energy for sensitive RF front-ends (e.g., near an antenna/LNA) or noisy sources (e.g., a switching converter that must not radiate into a nearby sensitive section) — the shield's ground perimeter needs continuous, low-impedance stitching (dense via fence) to be effective; gaps in the perimeter (for cable pass-throughs, component clearance) become leakage points and should be minimized/positioned away from the most sensitive or noisiest element inside.
- **Cable shielding**: shielded cable for any interconnect between the board and a remote sensor/actuator carrying low-level signals or leaving a controlled enclosure — terminate the shield at the connector's dedicated shield-ground contact (360° shield termination where the connector supports it, not a single pigtail wire, which is far less effective at high frequency) and follow the standard's/system's shield-grounding scheme (typically one end for low-frequency sensitive signals to avoid ground-loop current in the shield, both ends for high-frequency/EMC-critical cables to maintain shield continuity — the "single point vs both ends" choice depends on frequency content and system grounding architecture, and is a common point of disagreement even among experienced engineers; when in doubt, both-ends grounding with a solid overall system ground reference is the modern default recommendation for EMC compliance).
- **Enclosure-level shielding**: overall product enclosure material (metal vs plastic) and any seams/vents/gaps in it dominate the product's actual radiated emissions/immunity performance more than board-level measures alone for many designs — PCB-level EMC practice reduces the energy available to leak out, but enclosure design (seam gaskets, vent hole sizing relative to wavelength, cable shield bonding to the enclosure at entry) is often the deciding factor for final compliance.

## Pre-compliance testing

- **Conducted emissions**: measure noise current on power/signal cables (LISN-based measurement) against the applicable limit (e.g., CISPR 32 for multimedia equipment, CISPR 11 for industrial/ISM equipment) — this can often be approximated with a near-field probe or a simple LISN setup on the bench before full compliance testing, catching gross problems (missing decoupling, unfiltered switching noise on a cable) early and cheaply.
- **Radiated emissions**: measure field strength at a defined distance across a frequency range — pre-compliance can be approximated with a spectrum analyzer and a near-field probe scanning the board (identifies hot spots/radiating traces or components even without a calibrated far-field setup) or a low-cost pre-compliance chamber/open-area test site rental, before committing to a full accredited test lab session.
- **Immunity testing (ESD, EFT, surge, radiated/conducted immunity)**: IEC 61000-4-2 (ESD), -4-4 (EFT/burst), -4-5 (surge), -4-3 (radiated immunity), -4-6 (conducted immunity) form the core immunity test suite referenced by most product EMC standards — an ESD gun test on connectors and enclosure seams during development (even an inexpensive handheld ESD simulator) catches many protection-circuit gaps well before formal certification testing.
- Iterating with pre-compliance measurement during development (rather than only discovering problems at the accredited test lab) significantly reduces redesign cost and schedule risk — budget bench time for at least a basic near-field scan and an ESD gun check on any board with external connectors before finalizing layout.

## CISPR 32 / IEC 61000 overview

- **CISPR 32**: emission requirements for multimedia equipment (covers most modern electronic products with digital processing and often RF), specifying conducted emission limits (150 kHz–30 MHz typical range on power ports) and radiated emission limits (30 MHz–1 GHz and above, extending higher for equipment with higher internal clock frequencies) — Class A (industrial/commercial environment, more lenient limits) vs Class B (residential environment, stricter limits) distinction matters for which limit table applies; know which class your product is targeting from the start, since it affects filtering/shielding margin needed.
- **IEC 61000-6-x (generic immunity/emission standards)** and **IEC 61000-4-x (specific test methods)**: the 61000-6 series gives generic immunity (6-1/6-2) and emission (6-3/6-4) requirements for residential vs industrial environments, referencing the 61000-4-x series for the actual test methods (ESD, EFT, surge, radiated/conducted immunity, voltage dips, etc.) — industrial environment standards (61000-6-2 immunity, 61000-6-4 emission) generally require higher immunity levels but allow more emission than residential/light-industrial equivalents (61000-6-1/6-3), reflecting the harsher electrical environment but lower emission-sensitivity expectation in industrial settings.
- For a specific product category (medical, automotive, telecom, industrial control), a product-specific standard usually takes precedence over the generic 61000-6-x series and CISPR 32 — always check whether a more specific standard applies to the actual application before defaulting to the generic ones.

## Worked example: connector ESD/surge protection stack

A field-connected RS-485 port on an industrial board needs to survive IEC 61000-4-2 ESD (±8 kV contact) and IEC 61000-4-5 surge (1 kV common mode, since the cable run is moderate length indoors).

1. **First stage at the connector**: a bidirectional TVS diode array across each signal line (A, B) to the chassis/earth reference, standoff voltage above the RS-485 transceiver's normal common-mode operating range (typically rated for ±12 V or more common-mode already, so a TVS standoff around 15–17 V is reasonable), clamping voltage kept below the transceiver's absolute maximum bus voltage rating (many RS-485 transceivers tolerate ±60 V or more fault range, giving comfortable margin).
2. **Series impedance**: a small series resistor (e.g., 10–33 Ω) or a small ferrite bead between the TVS and the transceiver's bus pins, so that during a fast transient the TVS (not the transceiver's internal ESD structure) absorbs most of the current — this series impedance coordinates the two protection stages so the cheaper/more robust discrete TVS does the heavy lifting instead of relying on the transceiver IC's own limited internal ESD cell.
3. **Common-mode choke**: placed on the RS-485 pair right after the connector, ahead of the termination/bias network, to suppress common-mode noise coupled onto the cable from EFT-type events or nearby switching equipment, without distorting the differential RS-485 signal (choose a choke qualified for differential-pair signal integrity at the RS-485 baud rate in use).
4. **Layout**: TVS and choke placed within a few mm of the connector, TVS ground return routed with a short, low-inductance path to a chassis-stitched ground area (not through the sensitive digital ground plane), and no trace from the connector to the transceiver crosses any plane split.
5. **Verification**: bench-test with a handheld ESD simulator at the connector (both contact and air discharge per the target level) before committing to full accredited IEC 61000-4-2/4-5 compliance testing, to catch gross layout or component-selection problems early and cheaply.

## Common mistakes

- Relying solely on a series diode for reverse-polarity protection at significant current, wasting power and headroom that an ideal-diode MOSFET circuit would save.
- Placing ESD/TVS protection components with long lead/trace length from the connector, letting fast transients spike past the rated clamp voltage before the device can respond.
- Routing high-speed or high-di/dt traces across a plane split, creating a large return-current loop and a strong radiator/EMI-susceptible point.
- Using a single-pigtail cable shield termination on an EMC-critical interconnect instead of a proper 360° connector shield termination.
- Skipping any pre-compliance measurement during development and discovering emissions/immunity failures only at the accredited test lab, late in the schedule.
- Choosing Class B (residential) emission targets without realizing it, when the product could have qualified for the more lenient Class A (industrial) limits — or vice versa, under-margining a residential-market product against Class A limits.
- Assuming board-level shielding alone will meet compliance without considering the enclosure's own seams, vents, and cable-entry shield bonding.

## Schematic review checklist

- [ ] Reverse-polarity and overvoltage protection topology chosen appropriate to fault current, response-time, and efficiency needs (series diode vs ideal diode vs crowbar vs active OVP).
- [ ] ESD/TVS protection specified at every externally accessible connector pin, with device parameters matched to the relevant IEC 61000-4-2 test level.
- [ ] Low-capacitance ESD protection used on high-speed signal lines where standard TVS capacitance would degrade signal integrity.
- [ ] Common-mode chokes specified on cable entries where conducted/radiated common-mode noise is a concern, rated for the correct impedance curve and current without saturation.
- [ ] Shield termination scheme (single-end vs both-ends) chosen deliberately for each shielded cable interface, matched to its frequency content and grounding architecture.
- [ ] Target emission/immunity standard (CISPR 32 class, IEC 61000-6-x category) identified early, driving margin decisions throughout the design.

## Layout review checklist

- [ ] ESD/TVS/protection components placed immediately at connectors with short, low-inductance traces and a direct path to chassis/earth ground.
- [ ] No high-speed or high-di/dt trace crosses a plane split; stitching vias placed near any unavoidable reference-plane transition.
- [ ] Solid, uninterrupted reference plane maintained beneath every signal layer, especially under connectors and cable entries.
- [ ] Ground stitching vias placed at regular intervals (roughly λ/20 of highest frequency of concern) along board edges, around connectors, and around any plane splits/cutouts.
- [ ] Shielding can (if used) has a continuous, densely stitched ground perimeter with minimal gaps positioned away from the most sensitive/noisiest element.
- [ ] Cable shield terminated per the chosen scheme (360° connector termination preferred for EMC-critical interfaces).
- [ ] Common-mode chokes placed at the cable entry point, close to the connector, ahead of any sensitive downstream circuitry.
- [ ] Board has been checked with at least a basic near-field EMI scan and ESD gun test on connectors/seams before finalizing layout for production.
