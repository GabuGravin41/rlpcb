---
title: Analog and Mixed-Signal Circuit Design
domain: analog
tags: [op-amp, adc, anti-alias filter, reference, grounding, ground plane, sensor interface, guard ring, precision layout]
applies_to: [analog boards, mixed-signal boards, sensor/instrumentation boards, data acquisition systems]
---

## Op-amp circuit fundamentals for board design

- **Non-inverting amplifier**: signal → op-amp + input; feedback network from output through R_f to the − input, and R_g from the − input to ground. Gain = 1 + R_f/R_g. High input impedance (good for high-impedance sensors); output is in-phase with input.
- **Inverting amplifier**: signal → R_in → op-amp − input (virtual ground); feedback R_f from output to − input; + input tied to reference/ground. Gain = −R_f/R_in. Input impedance = R_in (lower, loads the source) — add a buffer stage ahead of it for high-impedance sources.
- **Difference/instrumentation amplifier**: rejects common-mode signal, amplifies only the differential signal between two inputs — essential for sensor signals referenced across a distance (strain gauges, thermocouples, current-shunt sensing) where ground potential differs between source and amplifier. Use a dedicated in-amp IC (three-op-amp topology integrated) rather than discrete op-amps for anything precision-sensitive — matching of discrete resistor networks is rarely good enough for high CMRR.
- **Selecting resistor values**: keep feedback network resistances in the 1 kΩ-to-100 kΩ range typically — too low wastes power and loads the output excessively; too high increases Johnson noise (thermal noise voltage ∝ √(4kTRB)) and makes the circuit more sensitive to input bias current errors and PCB leakage currents.
- **Bandwidth/gain-bandwidth product (GBW)**: required closed-loop bandwidth × required gain must stay well below the op-amp's GBW (rule of thumb: choose an amplifier with GBW ≥ 10x the needed closed-loop bandwidth at the design gain, more margin for multi-pole/filter applications where phase margin at the signal band matters).
- **Rail-to-rail vs standard**: rail-to-rail input/output op-amps are needed when signal swings close to supply rails (common in single-supply designs); check the specific input stage architecture's crossover distortion region if the signal crosses the input common-mode crossover point (some rail-to-rail input designs have a small linearity glitch near mid-supply).
- Decouple every op-amp's supply pins locally per power_decoupling_and_pdn.md — op-amp PSRR is finite and degrades at higher frequency, so supply noise directly couples to the output if not filtered locally.

## ADC front-end design

- **Driving the ADC input**: most SAR ADCs need a low-impedance source to charge their internal sample-and-hold capacitor within the sampling window — a dedicated ADC driver op-amp (wide bandwidth, low output impedance, fast settling) between the signal conditioning chain and the ADC input is standard practice, not optional, for anything beyond slow/low-resolution ADCs.
- **RC anti-alias/charge-kickback filter**: a small series R (tens of ohms) and shunt C (tens to hundreds of pF) directly at the ADC input, in addition to any earlier anti-alias filter stage, absorbs the SAR ADC's sampling-capacitor charge-injection transient and provides final band limiting — check the specific ADC's recommended RC values in its datasheet (often given explicitly, e.g., in TI/ADI SAR ADC driving app notes such as TI SBAA jjj-series or ADI MT-xxx tutorials).
- **Differential vs single-ended input**: differential ADC inputs reject common-mode noise and effectively double dynamic range for a given supply — preferred for precision measurement; requires a differential driver (dedicated diff-amp IC or a transformer for AC-coupled signals) ahead of the ADC.
- **Reference**: ADC accuracy is only as good as its reference's accuracy, noise, and drift — see power_linear_regulators_and_references.md for reference selection; decouple the reference pin per datasheet immediately at the pin, with a short, direct trace.
- **Grounding the ADC**: many precision ADCs provide separate AGND/DGND pins that must be tied together at a single point (usually directly under/near the package, per the datasheet's recommended layout) — do not connect them separately to different plane regions that later join elsewhere, as this creates a ground loop through the ADC package itself.

## Anti-alias filtering

- Nyquist criterion: any signal content at or above half the sampling rate (fs/2) aliases back into the baseband and cannot be distinguished from real signal — an anti-alias low-pass filter ahead of the ADC must attenuate content above fs/2 to below the ADC's noise floor (i.e., below 1 LSB-equivalent noise, roughly -6.02×N dB for an N-bit ADC's full-scale range, though real achievable dynamic range is usually less than the ideal quantization limit due to noise).
- Filter order/topology: a simple single-pole RC filter is often inadequate for oversampling-margin-limited systems (steep transition band needed) — multi-pole active filters (Sallen-Key, multiple-feedback) or a higher decimation-ratio oversampling ADC (which relaxes the analog anti-alias requirement because the effective Nyquist frequency is pushed much higher, letting a gentle single-pole filter suffice) are the two common strategies; oversampling delta-sigma ADCs are popular specifically because they simplify the anti-alias filter requirement.
- Filter cutoff placement: set well below fs/2 with margin for the filter's own transition band and for the actual signal bandwidth of interest — e.g., if signal bandwidth is 1 kHz and fs = 10 kHz (fs/2 = 5 kHz), a filter with cutoff around 1–2 kHz and enough order to reach sufficient attenuation by 5 kHz is typical; the exact numbers depend on required dynamic range and available oversampling margin.
- Passive vs active: passive RC/LC filters are simple and noiseless (no added active-device noise) but have limited roll-off steepness per stage and can load the source; active filters (op-amp based) give steeper roll-off and buffer the source, at the cost of added noise and power.

## Grounding: split vs unified plane

The historically common advice to physically split analog and digital ground planes (AGND/DGND as separate copper pours joined at one point) is now generally considered outdated for most mixed-signal boards, and is actively discouraged by current application notes from major analog IC vendors (e.g., Analog Devices MT-031, MT-101 tutorials, TI mixed-signal layout guides) **except in specific cases**:

- **Prefer a single, unified ground plane** for most mixed-signal boards, with **partitioning by placement and routing discipline** instead of a physical plane split: place analog circuitry in its own region of the board, digital circuitry in another, route digital return currents so they don't cross under/through the analog region, and let the single solid plane provide the lowest-impedance return path for all signals.
- A physically split ground plane, if a return current is forced to cross the split (e.g., a signal trace routed over the gap), creates a large return-path loop (the current has to detour around the split to get back), which is worse for EMI and noise coupling than a solid plane would have been — this is the core reason unified planes with careful placement usually outperform naive splits.
- **When a true split is still justified**: crossing an isolation boundary (galvanically isolated domains, see industrial_plc_io.md), or very specific high-precision instrumentation layouts where the vendor's own reference design explicitly specifies a split with a defined single-point (star) connection — follow that specific reference design's join-point location exactly if so, rather than improvising.
- Practical mixed-signal floorplanning: place the ADC straddling the analog/digital boundary (analog pins toward the analog region, digital/interface pins toward the digital region), keep the "noisy" digital return current (from clocks, buses, switching regulators) from ever flowing under the analog section, and use plane stitching/decoupling per power_decoupling_and_pdn.md throughout.

## Guard rings

Guard rings protect ultra-high-impedance nodes (electrometer-grade op-amp inputs, photodiode transimpedance amplifier inputs, pH/ion-sensing electrodes, charge amplifiers) from PCB surface leakage current, which can be significant compared to picoamp-to-femtoamp-level input bias currents at these nodes.

- A guard ring is a copper trace/pour surrounding the sensitive high-impedance node, driven to the **same potential** as that node (typically buffered from the node itself via a unity-gain buffer, or directly from the op-amp's own input in some transimpedance topologies) — since there's no voltage difference between the guard and the sensitive node, no leakage current flows between them across the PCB surface, intercepting leakage current that would otherwise have flowed from a nearby biased trace into the sensitive node.
- Guard ring must fully surround the sensitive trace/pad on all layers where leakage could occur (top and bottom if the sensitive trace is exposed on both, or at minimum on the layer the sensitive trace/pad is routed on) — a partial guard ring leaves a leakage path around the gap.
- Keep the guard ring's own drive impedance low (buffered, not just resistively derived) so it can actually track the guarded node's potential without lag/error.
- Also apply general leakage mitigation regardless of guard rings: keep high-impedance nodes away from any high-voltage or fast-switching trace, minimize solder mask contamination/flux residue near these nodes (board cleanliness matters more here than on ordinary digital nodes), and consider removing solder mask and using an air gap or a milled slot around an extremely sensitive pad in the most demanding designs (electrometer-grade, <1 pA leakage budgets).

## Sensor interfaces

- **Resistive bridge sensors (strain gauge, load cell, pressure)**: typically Wheatstone bridge configuration, driven by a stable excitation voltage/current, output taken differentially and amplified by an instrumentation amplifier — use a ratiometric reference (ADC reference derived from the same excitation source) where possible so excitation drift cancels out in the ratio rather than needing separate high-precision excitation and reference sources.
- **Thermocouples**: generate a small (µV/°C) voltage requiring cold-junction compensation (a local temperature sensor at the point where thermocouple wire meets copper PCB trace, since that junction itself generates a parasitic thermocouple voltage) — many thermocouple interface ICs integrate cold-junction compensation; if building discrete, place the cold-junction temperature sensor physically as close as possible to the actual thermocouple wire termination point, and keep both terminal pads at the same temperature (thermally coupled, e.g., same copper pour, away from hot components).
- **RTDs (resistance temperature detectors)**: use 3-wire or 4-wire (Kelvin) connections to cancel lead-wire resistance error — 2-wire RTD connections introduce lead resistance directly into the temperature reading and are only acceptable for very short leads/low-precision needs.
- **Photodiodes/transimpedance amplifiers**: photodiode connected across an op-amp's inverting input and output through a feedback resistor (transimpedance gain = R_f), with the photodiode's other terminal to ground/reference — this is a classic guard-ring application given the very high input impedance and low bias-current requirement; also watch feedback capacitance (a small C_f in parallel with R_f is often needed for stability, since the photodiode's junction capacitance combined with the amplifier's input capacitance can create a destabilizing pole).
- **Capacitive/inductive sensors (proximity, level, position)**: often need dedicated sensor-interface ICs (capacitance-to-digital or LDC-style inductance-to-digital converters) due to the small signal levels and parasitic sensitivity involved — discrete implementation is possible but layout parasitics (stray capacitance to ground, cable capacitance) dominate performance more than in most other sensor types, so shielding/guarding and short sensor-to-electronics distance matter even more.

## Precision layout practices

- **Star grounding at the local level**: even within a unified plane philosophy, sensitive precision circuits (voltage references, precision op-amp feedback networks) benefit from having their local return currents converge at a single point before joining the broader plane, minimizing the chance that another circuit's return current flows through the sensitive circuit's local ground path.
- **Trace symmetry for differential signals**: route differential pairs (instrumentation amp inputs, differential ADC inputs) with matched length and matched spacing to nearby copper/vias on both traces — asymmetry converts common-mode noise into differential-mode error, defeating the purpose of differential signaling.
- **Avoid routing sensitive analog traces under/near crystal oscillators, switching regulators, or digital buses** — even a plane between them helps, but physical distance and orientation (crossing digital traces at 90° if unavoidable, never running parallel alongside for a long distance) reduce capacitive/inductive coupling.
- **Component placement order for a precision chain**: place the sensor/connector first, then signal-conditioning (instrumentation amp, filter), then ADC, in as straight and short a path as layout allows — minimizes trace length exposure to noise at each vulnerable stage, especially before the signal has been amplified above the noise floor.
- **Via and pad symmetry**: for matched-impedance or matched-delay differential/precision traces, keep via count and pad geometry identical on matched pairs — an extra via on only one side of a pair adds asymmetric delay/impedance discontinuity.
- **Thermal gradients**: precision analog circuits (references, instrumentation amps) are sensitive to temperature gradients across the board (thermocouple effect at dissimilar-metal junctions, and component tempco) — keep heat-generating components (regulators, high-current traces) away from precision analog sections, and consider board orientation/airflow if a thermal gradient across a differential pair or bridge would introduce measurable error.

## Worked example: anti-alias filter for an oversampling ADC

A delta-sigma ADC samples internally at fs = 2 MHz with an oversampling ratio (decimation) that places the effective Nyquist consideration for the analog anti-alias filter near the modulator sampling frequency rather than the final output data rate — this is the standard advantage of oversampling converters. Signal bandwidth of interest is 0–1 kHz (e.g., a slow process/temperature measurement).

1. Because the modulator itself samples at 2 MHz, a simple single-pole RC filter with cutoff well above the 1 kHz signal band (e.g., set at 10–20 kHz, giving ample passband flatness margin) but far below 2 MHz already provides enough attenuation by the time you reach the modulator's actual sampling frequency — this is why oversampling ADCs are popular for simplifying anti-alias filtering versus a traditional Nyquist-rate SAR ADC.
2. Compute RC: for cutoff fc = 15 kHz, using a standard R = 1 kΩ, C = 1/(2π×fc×R) = 1/(2π×15,000×1,000) ≈ 10.6 nF — round to a standard 10 nF or 12 nF.
3. Contrast with a Nyquist-rate SAR ADC sampling directly at, say, fs = 10 kHz for the same 1 kHz signal bandwidth: fs/2 = 5 kHz, leaving only a 5x margin between signal band (1 kHz) and Nyquist (5 kHz) — a single RC pole is unlikely to provide enough attenuation by 5 kHz, requiring a steeper multi-pole active filter (e.g., a 2nd or 3rd order Sallen-Key) instead, illustrating directly why oversampling relaxes the analog filter requirement.
4. Regardless of topology, place the final RC (kickback/settling) filter directly at the ADC input per the datasheet's recommended values, in addition to this signal-bandwidth anti-alias stage — the two serve different purposes (macroscopic anti-aliasing vs local charge-injection absorption) and both are typically present in a well-designed front end.

## Common mistakes

- Splitting ground planes reflexively "because that's what mixed-signal boards do," without recognizing this can create larger return-current loops than a well-partitioned unified plane.
- Driving a SAR ADC input directly from a high-impedance source without a driver amplifier and RC filter, causing settling errors and non-linearity.
- Using single-ended sensing for a signal whose source ground differs from the ADC's ground reference, introducing ground-potential-difference error.
- Omitting cold-junction compensation on a discrete thermocouple interface, or placing the compensation sensor far from the actual junction.
- Using 2-wire RTD connections when 3- or 4-wire accuracy is actually required for the application's tolerance budget.
- Forgetting a guard ring (or any leakage mitigation) on femtoamp/picoamp-level input nodes, leading to inexplicable drift or offset that varies with humidity/contamination.
- Routing differential pair traces with mismatched length/spacing, converting common-mode noise into a differential error term.
- Placing precision analog components near heat-generating parts, introducing thermal-gradient-driven offset drift.

## Schematic review checklist

- [ ] Op-amp gain-bandwidth product has adequate margin (≥10x) over the required closed-loop bandwidth at the design gain.
- [ ] ADC driver amplifier and RC anti-alias/charge-kickback filter present and sized per the specific ADC's datasheet recommendation.
- [ ] Anti-alias filter order/cutoff justified against the sampling rate, oversampling ratio, and required dynamic range.
- [ ] Sensor interface topology (bridge, thermocouple+CJC, RTD wire count, transimpedance) matches the sensor type's accuracy requirements.
- [ ] Reference decoupling and routing follow power_linear_regulators_and_references.md.
- [ ] Guard ring or equivalent leakage mitigation specified for any sub-nanoamp input-current node.
- [ ] Differential signal paths (in-amp inputs, differential ADC inputs) identified for matched-length/matched-spacing layout.

## Layout review checklist

- [ ] Ground plane strategy (unified with partitioning, or justified split) documented and followed consistently across the board.
- [ ] Analog and digital circuit regions physically separated with return-current flow considered, not just component placement.
- [ ] ADC AGND/DGND tied per the specific datasheet's single-point recommendation.
- [ ] Guard rings fully enclose sensitive high-impedance nodes on all relevant layers, driven at matching potential.
- [ ] Differential pairs routed with matched length and symmetric via/pad structure.
- [ ] Precision analog components placed away from heat sources and high-current/switching traces.
- [ ] Signal chain placement order (sensor → conditioning → ADC) is short and direct, avoiding unnecessary trace length before amplification.
- [ ] No sensitive analog trace routed parallel and adjacent to a digital bus or switching-regulator trace for a significant distance.
