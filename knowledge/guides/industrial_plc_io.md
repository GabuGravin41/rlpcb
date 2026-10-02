---
title: Industrial PLC and Field I/O Design
domain: industrial
tags: [plc, iec 61131-2, digital io, analog io, 4-20ma, 0-10v, isolation, rs-485, modbus, can, surge, tvs, creepage, clearance]
applies_to: [industrial control boards, plc modules, field io boards, sensor interface boards]
---

## Digital inputs: IEC 61131-2 types

IEC 61131-2 defines standard 24 VDC digital input characteristics so field devices (sensors, switches) interoperate predictably across vendors.

- **Type 1**: lower input current (nominal ~2 mA at 24 V, i.e., higher input impedance, ~15 kΩ+), suited for driving longer cable runs and interfacing with electromechanical/reed switches and low-power sensors without excessive loading.
- **Type 2/Type 3**: higher input current (Type 3 nominal current ~2–15 mA range at 24 V depending on sub-type), lower impedance, more noise-immune and better suited for driving 2-wire proximity/photoelectric sensors that need a minimum holding current to stay in their "on" state — check the sensor's minimum load current spec against the PLC input's sink current at the sensor's expected "on" voltage.
- Threshold voltages (typical, verify against the specific edition/type): input recognized "OFF" below ~5 V, "ON" above ~15 V, for a nominal 24 V system — leaving a defined hysteresis band for noise immunity.
- Standard input signal chain: field terminal → series input resistor (sets input impedance/current, also provides some protection) → RC/TVS filtering for surge/noise → optocoupler or digital isolator → logic-level signal to MCU/PLC CPU. The optocoupler/isolator provides galvanic isolation between the noisy, potentially high-energy field wiring and the sensitive control electronics — treat this isolation as mandatory for any field-connected digital input on an industrial board, not optional.
- Debounce (RC filter, typically a few ms time constant) is standard on mechanical contact inputs to avoid multiple logic transitions from contact bounce.

## Digital outputs: sinking vs sourcing

- **Sourcing (PNP) output**: output switches the +24 V supply to the load; load's other terminal returns to 0 V/common. Common in European/IEC-influenced industrial practice.
- **Sinking (NPN) output**: output switches the 0 V/common connection to the load; load's other terminal connects to +24 V. Common in North American practice and some sensor ecosystems.
- A board's I/O must match the field device's wiring convention — mismatching sourcing outputs with sinking-expecting devices (or vice versa) simply doesn't work; always specify and label which type each I/O channel is.
- **High-side switch ICs** (integrated smart high-side drivers, e.g., automotive/industrial parts with built-in current limiting, thermal shutdown, and diagnostic feedback) are the standard modern approach for sourcing digital outputs — they replace a discrete high-side MOSFET + charge pump + protection circuit with a single part, and provide a diagnostic output (fault flag) useful for PLC self-diagnostics.
- **Low-side switch (NPN/N-channel FET) outputs**: simpler (no need to drive the gate above the rail), commonly used for sinking outputs; still need a flyback diode for inductive loads (relay coils, solenoid valves) and short-circuit/overcurrent protection.
- Relay outputs: electromechanical relays provide the simplest galvanic isolation and can switch AC or DC loads, but have limited switching life (mechanical, typically 100k–10M cycles depending on load) and slower switching speed — use solid-state relays (SSRs, opto-triac or opto-MOSFET based) for high-cycle-count or fast-switching applications, noting SSRs typically have higher on-state voltage drop/loss and need their own thermal design.
- Include flyback diodes or snubbers on every relay coil and inductive output load — see power_high_current_and_thermal.md.

## Analog I/O: 4–20 mA current loop

- **Why current loop**: current signals are immune to voltage drop over long cable runs (unlike a 0–10 V signal, which loses accuracy over resistance-significant cable lengths) and inherently support wire-break detection (0 mA = broken wire/fault, distinguishable from a valid 0% signal which is 4 mA, not 0 mA — this "live zero" is the core reason 4–20 mA uses 4 mA as the zero point, not 0 mA).
- **2-wire (loop-powered) transmitters**: the same two wires carry both power to the transmitter and the signal — the transmitter modulates its own current draw between 4–20 mA to represent the measured value. The receiving PLC/input module provides loop power (commonly 24 V) and measures the loop current via a precision sense resistor (commonly 100–250 Ω, chosen so the voltage drop at 20 mA, 2–5 V, doesn't exceed the loop's available compliance voltage after accounting for cable resistance and transmitter's own minimum operating voltage).
- **4-wire (separately powered) transmitters**: separate power supply and separate 2-wire signal output — used when the transmitter's own power draw doesn't fit within loop-power constraints.
- Receiving circuit: current loop → precision burden/sense resistor → differential/instrumentation amplifier (or direct into an isolated ADC front end) → isolation (if the loop is field-referenced and the PLC logic is isolated) → ADC.
- HART protocol (superimposed digital FSK signal on top of the 4-20 mA analog current) is common in process instrumentation for configuration/diagnostics alongside the primary analog value — if supporting HART, include the appropriate loop impedance (typically requiring ≥230 Ω total loop resistance for HART communication) and a HART modem IC if you need to decode it.

## Analog I/O: 0–10 V

- Simpler than current loop but sensitive to cable resistance-induced voltage drop and ground-potential differences over long runs or between separately-grounded equipment — best for shorter cable runs within the same enclosure/cabinet, or where the extra transmitter cost of current-loop isn't justified.
- Input protection: series resistor + clamping diodes/TVS to protect the ADC input from overvoltage field faults (a field wire shorted to a higher voltage source is a realistic fault mode to design against).
- Differential (rather than single-ended) 0–10 V input sensing rejects ground-potential-difference errors between the source and the PLC input common — preferred in noisy industrial environments.
- Output side: a DAC followed by an op-amp buffer capable of driving the expected cable + load impedance at the full 0–10 V range with adequate current (check the receiving device's input impedance, commonly ≥10 kΩ, so load current is typically small, but the driving op-amp still needs adequate output current capability and short-circuit protection since field wiring can be shorted).

## Isolation

Isolation separates two circuit domains (e.g., field wiring vs control logic, or two independently grounded systems) so that voltage differences, ground faults, or transients on one side don't damage or corrupt the other.

- **Digital isolators** (capacitive or magnetic coupling based, e.g., ISO7741-style parts): replace optocouplers for digital signal isolation with higher speed, better reliability (no LED degradation over life), and often multi-channel integration. Choose working voltage rating (Vrms working isolation voltage) and surge withstand rating appropriate for the application's isolation requirement — a "reinforced" or "double" isolation rating is required where basic isolation is insufficient for safety (e.g., mains-adjacent or hazardous-voltage-adjacent circuits per IEC 62368-1), not just "reinforced" for physical robustness but for regulatory compliance.
- **Isolated DC-DC converters**: provide power across the isolation barrier (since an isolated digital signal still needs power on both sides) — choose isolation voltage rating and creepage/clearance of the isolated DC-DC module consistently with the digital isolator's rating; mismatching (e.g., a high-isolation digital isolator paired with a low-isolation-voltage DC-DC converter) creates a weak link that defeats the purpose.
- **Analog isolation**: isolated amplifiers or isolated ADCs (modulator on the field side, isolated digital output) for analog signals needing galvanic isolation — more complex than digital isolation due to the need to preserve signal linearity/accuracy across the barrier; check isolation-mode rejection and gain/offset drift specs.
- Isolation is required (not just good practice) wherever field wiring can carry hazardous voltage, wherever ground loops between separately-earthed equipment must be broken, or wherever safety standards for the application (e.g., IEC 61131-2 for PLC I/O in some configurations, IEC 62368-1 for general electronic equipment safety) mandate it.

## Serial industrial buses

- **RS-485 / Modbus RTU**: differential, multi-drop, half-duplex (typically) serial bus, robust over long cable runs (up to ~1200 m at lower baud rates) and noisy environments due to differential signaling. Termination: 120 Ω resistor at each end of the bus (not at every node) matching the cable's characteristic impedance; failsafe biasing resistors (typically a pull-up on A/non-inverting and pull-down on B/inverting, sized so idle-bus voltage sits in a defined "mark" state, commonly a few hundred ohms to a few kΩ depending on the number of nodes on the bus) prevent false data during idle/high-impedance bus states. Modbus RTU is the common application-layer protocol riding on RS-485 in industrial automation.
- **CAN (Controller Area Network)**: differential, multi-drop, message-based arbitration (not master-slave), used widely in industrial and automotive/motion control (see motor_drives_and_motion.md for CAN-FD in robotics/actuator contexts). 120 Ω termination at each of the two bus ends. CAN transceivers provide the differential drive; isolated CAN transceivers/isolated DC-DC are used where the CAN segment crosses an isolation boundary.
- **EtherCAT / industrial Ethernet PHY basics**: industrial Ethernet variants (EtherCAT, PROFINET, EtherNet/IP) use standard Ethernet PHY silicon and magnetics but require attention to: PHY clock/timing accuracy for real-time determinism (EtherCAT processes frames on-the-fly through each node, so latency/jitter budget matters more than in standard IT Ethernet), robust magnetics (isolation transformers rated for the environment), and often redundant/ring topology support (dual PHY ports per node for daisy-chaining, common in EtherCAT slave devices). Follow the specific protocol's conformance/certification test requirements (e.g., EtherCAT Technology Group conformance test) for the PHY and magnetics selection rather than generic Ethernet design rules alone.
- All field-bus transceivers connected to cabling leaving the enclosure need surge/ESD protection at the connector (see below) — the transceiver IC's own ESD rating (often only a few kV per IEC 61000-4-2 contact discharge) is not sufficient on its own for field-wiring exposure; add board-level TVS protection.

## Surge, EFT, and ESD protection (IEC 61000-4-x)

Industrial field I/O must survive standardized transient immunity tests, commonly specified per equipment class:

- **IEC 61000-4-2 (ESD)**: contact discharge (typically tested to ±4 kV or ±8 kV depending on equipment class) and air discharge (±8 kV or ±15 kV) applied to accessible connectors/enclosure. Protect with TVS diodes at every field-accessible connector pin, placed as close to the connector as possible (before any sensitive IC), with a low-inductance ground return to the chassis/earth reference.
- **IEC 61000-4-4 (Electrical Fast Transient/Burst, EFT)**: fast repetitive burst transients (typically 2–4 kV on power lines, lower on signal/control lines) simulating relay/contactor switching noise on nearby wiring. Common-mode chokes on cable entries plus TVS/clamping at the connector are the standard mitigation.
- **IEC 61000-4-5 (Surge)**: simulates lightning-induced or switching surges on longer cable runs (typically 1–2 kV differential mode, 2–4 kV common mode on outdoor/long-run signal and power lines). Requires higher-energy TVS or gas discharge tube (GDT) protection (GDTs handle higher energy surges than TVS diodes alone but have slower response time and a follow-current concern on DC circuits — a common protection scheme uses a GDT for coarse/high-energy clamping plus a downstream TVS diode for fast clamping, coordinated via a series impedance so the TVS doesn't have to absorb the full surge energy alone).

## TVS selection

- Choose TVS **standoff voltage** (Vwm, the voltage below which the TVS does not conduct) above the maximum normal operating voltage of the line (including tolerance/ripple), with margin — e.g., for a nominal 24 V field-supply line with ±10% tolerance, standoff voltage should exceed ~26.4 V, commonly a 26–30 V standoff part is chosen.
- Choose **clamping voltage** (Vc, the voltage across the TVS at its rated peak pulse current) below the downstream protected device's absolute maximum voltage rating, with margin.
- Choose **peak pulse power/current rating** based on the specific standard's test waveform and level (e.g., 8/20 µs waveform for IEC 61000-4-5 surge, specific IEC 61000-4-2 ESD waveform) — TVS datasheets typically publish peak pulse power vs pulse duration curves; size for the actual test waveform's energy, not just a generic "high power" part.
- Bidirectional TVS for AC or signal lines that swing both polarities; unidirectional for DC rails where only positive (or only negative) transients are relevant, which also allows lower clamping voltage for the same standoff (unidirectional parts clamp closer to Vwm than bidirectional parts of the same rating).
- Place TVS as physically close to the connector/entry point as possible, with the shortest possible ground/return trace — TVS effectiveness is significantly degraded by trace inductance between the connector and the TVS (a long lead/trace lets the protected voltage spike higher than the TVS's rated clamping voltage during the fast rise time of ESD/EFT events).

## Creepage and clearance

- **Clearance**: shortest distance through air between two conductors at different potential.
- **Creepage**: shortest distance along the surface of the insulating material between two conductors at different potential.
- Required distances scale with working voltage, pollution degree (environmental contamination level, typically Pollution Degree 2 for enclosed industrial equipment, Pollution Degree 3 for exposed/dirty environments), and material CTI (comparative tracking index) of the PCB/connector material — governed by IEC 60664-1 (general low-voltage) and referenced by product safety standards like IEC 62368-1 and UL 508 (industrial control equipment) for specific creepage/clearance tables.
- Typical starting reference (Pollution Degree 2, basic insulation, ≤50 V RMS/DC working voltage): clearance and creepage each around 0.2–0.8 mm range depending on the exact standard/table; these grow substantially at mains voltage (e.g., 250 VAC working voltage commonly needs several mm of both) — always look up the specific table for your working voltage and insulation class (basic/supplementary/reinforced) rather than assuming a single number applies across the whole board.
- On the PCB itself, achieve required creepage with slots/routed gaps between high-voltage and low-voltage regions when required distance exceeds what flat spacing alone provides in the available board area — a slot forces the creepage path around it, effectively multiplying the available surface distance in a compact footprint.
- Conformal coating can, under specific standard allowances, permit reduced spacing requirements (coated boards are sometimes treated as having a lower effective pollution degree) — this is standard-specific and coating-process-specific (coating must reliably cover and bridge the relevant gap); do not assume coating alone justifies reduced spacing without checking the applicable standard's coating provisions.

## Field-wiring connectors and conformal coating

- Use connectors rated for the field environment: screw-terminal or spring-cage terminal blocks rated for the wire gauge and current expected, with adequate voltage rating and creepage/clearance between adjacent terminals.
- Label/silkscreen polarity and signal type clearly at each field terminal — field wiring errors (miswiring 24 V into a signal input) are a common failure mode, and clear labeling plus input protection (TVS, series resistance, reverse-polarity protection) reduces the consequence.
- Conformal coating (acrylic, urethane, silicone, or parylene) protects against humidity, dust, and contamination common in industrial environments — select coating type based on rework needs (acrylic is easiest to rework/remove, silicone offers good flexibility/thermal range, urethane offers strong chemical resistance, parylene offers the most uniform/thinnest conformal coverage but requires specialized vapor-deposition equipment). Mask connectors, test points, and any component requiring later access before coating.

## Worked example: 4-20mA receiver burden resistor and TVS selection

**Burden resistor for a 2-wire 4-20 mA loop, 24 V loop supply, transmitter minimum operating voltage 10 V, 300 m of 0.5 mm² cable (≈0.08 Ω/m loop resistance, so ≈24 Ω round-trip at 300 m):**

1. Available compliance voltage for the burden resistor at max current (20 mA): Vavailable = Vsupply − Vtransmitter(min) − (Iloop × Rcable) = 24 − 10 − (0.020 × 24) = 24 − 10 − 0.48 ≈ 13.5 V.
2. Maximum burden resistor: R_burden(max) = Vavailable / I(max) = 13.5 / 0.020 ≈ 675 Ω.
3. Choose a standard precision burden resistor comfortably below this max, e.g., 250 Ω (a common standard value giving a clean 1–5 V output range across 4–20 mA: 4 mA×250Ω=1V, 20 mA×250Ω=5V), leaving margin for cable resistance tolerance and transmitter minimum-voltage variation. If HART communication is required, verify total loop resistance (including this burden) stays at or above the ~230 Ω minimum HART needs to communicate reliably, and this 250 Ω burden alone already satisfies that.
4. Measure the voltage across the burden resistor with a differential ADC input or instrumentation amplifier referenced correctly to the loop's ground scheme.

**TVS for the same field terminal, IEC 61000-4-5 surge, 1 kV differential mode test level, 24 V nominal loop:**

1. Standoff voltage: choose above 24 V × 1.1 (tolerance) ≈ 26.4 V — pick a 26–30 V standoff unidirectional or bidirectional TVS (bidirectional if loop polarity isn't guaranteed fixed relative to the TVS orientation).
2. Clamping voltage: verify the TVS's clamping voltage at its rated peak pulse current stays below the downstream amplifier/ADC's absolute maximum input rating (commonly a few volts above its supply rail) — if it doesn't, add a series resistor between the TVS and the sensitive input to share the clamp let-through voltage, or choose a lower-clamping-voltage part.
3. Peak pulse power: read the TVS datasheet's power-vs-pulse-duration curve at the 8/20 µs waveform point (the IEC 61000-4-5 surge test waveform) and confirm it exceeds the expected surge energy for the installation's exposure category (indoor, short cable run = lower energy requirement; outdoor or long cable run exposed to induced surges = higher, sometimes requiring a GDT + TVS coordinated pair as described above).
4. Place this TVS at the field terminal block, before the burden resistor and amplifier, with the shortest possible trace to both the terminal and to the chassis/earth return.

## Common mistakes

- Mixing sourcing and sinking I/O conventions without clear labeling, leading to field wiring errors.
- Omitting galvanic isolation on field-connected digital/analog I/O, exposing control electronics directly to field wiring faults and ground differences.
- Using 0-10V analog signaling over long cable runs where 4-20mA current loop would have been immune to voltage drop and enabled wire-break detection.
- Placing TVS protection components far from the connector (long trace/lead), which lets fast transients spike past the TVS's rated clamp voltage before it can respond.
- Terminating RS-485/CAN buses at every node instead of only at the two physical ends, causing signal reflections and communication errors.
- Missing failsafe bias resistors on RS-485, causing indeterminate/noisy bus states when idle.
- Underestimating creepage/clearance requirements for the actual working voltage and pollution degree, especially in compact PLC I/O modules.
- Assuming a digital isolator's rating alone protects the system when the accompanying isolated DC-DC converter has a lower isolation rating.

## Schematic review checklist

- [ ] Each digital I/O channel's sinking/sourcing convention specified and matched to intended field devices.
- [ ] Digital inputs include series impedance, filtering, and galvanic isolation (opto or digital isolator) before reaching logic.
- [ ] Inductive output loads (relays, solenoids) have flyback diodes/snubbers.
- [ ] Analog input signal chain (4-20mA burden resistor or 0-10V protection/buffer) sized and protected against field overvoltage faults.
- [ ] Isolation working voltage and surge rating (digital isolator + isolated DC-DC) are consistent and meet the application's safety requirement.
- [ ] RS-485/CAN bus has termination resistors defined (at bus ends only) and, for RS-485, failsafe bias resistors.
- [ ] TVS devices specified at every field-accessible connector pin with standoff/clamping voltage and pulse rating matched to the relevant IEC 61000-4-x test level.
- [ ] Creepage/clearance requirements identified for the working voltage and pollution degree of each isolation boundary on the board.

## Layout review checklist

- [ ] TVS and other transient-protection components placed immediately at the connector, with short, low-inductance ground return.
- [ ] Isolation barrier maintained as a clear board keep-out with correct creepage/clearance distance (slots added if needed) between field-side and logic-side copper/components.
- [ ] RS-485/CAN termination resistors physically placed at the bus's physical end nodes, not arbitrarily.
- [ ] Field wiring connectors labeled clearly on silkscreen (polarity, signal type, voltage).
- [ ] Common-mode chokes/EFT mitigation components placed at cable entry points.
- [ ] Conformal coating mask/keepout defined for connectors, test points, and adjustment components.
- [ ] High-voltage/low-voltage regions physically separated with routed slots where flat spacing is insufficient for required creepage.
- [ ] Ground/earth reference for TVS and chassis connections routed with adequate copper (low impedance) back to the actual earth/chassis point.
