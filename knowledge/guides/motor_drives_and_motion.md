---
title: Motor Drives and Motion Control Systems
domain: industrial
tags: [bldc, stepper, gate driver, bootstrap, dead time, shunt sensing, encoder, foc, can-fd, robotics, emi]
applies_to: [motor drive boards, robotics actuator boards, conveyor/elevator control, industrial motion systems]
---

## Motor type and driver topology overview

- **Brushed DC**: simplest, driven by a single H-bridge (4 switches). Direction and speed via PWM duty cycle and switch pairing. No commutation electronics needed (mechanical commutator does it), lowest system complexity, but brushes wear and generate electrical/mechanical noise.
- **Stepper (bipolar/unipolar)**: driven by one H-bridge per winding (2 H-bridges for a bipolar 2-phase stepper), stepped through current patterns (full-step, half-step, or microstepping with sinusoidal current profiles for smoothness). Open-loop position control by default (counts steps, no feedback) — closed-loop stepper systems add an encoder for stall detection/correction.
- **BLDC (trapezoidal/6-step commutation)**: 3-phase inverter (6 switches), commutated based on rotor position (Hall sensors or sensorless back-EMF zero-crossing detection) in six discrete steps per electrical revolution. Simpler control than FOC, adequate for many fan/pump/basic actuator applications, but produces torque ripple at commutation transitions.
- **PMSM/BLDC with FOC (Field-Oriented Control)**: same 3-phase inverter hardware as trapezoidal BLDC, but controlled with sinusoidal current vectors computed via Clarke/Park transforms referenced to actual rotor angle (from encoder, resolver, or sensorless observer) — produces smooth torque, higher efficiency, and precise current/torque control, at the cost of more complex control firmware and (usually) a real position/angle sensor.

Choose brushed DC for simple, low-cost, low-duty-cycle actuation; stepper for precise open-loop positioning at moderate speed/torque (3D printers, CNC, simple indexing); BLDC trapezoidal for efficient, brushless, moderate-performance drives (fans, pumps, e-bikes); FOC-controlled PMSM/BLDC for high-performance, smooth, precise torque/speed control (robotics actuators, servo drives, EVs).

## Gate drivers and bootstrap circuits

Every half-bridge (the building block of H-bridges and 3-phase inverters) needs the high-side switch's gate driven above the switch-node voltage, which itself swings up to the bus voltage — this requires a floating gate drive supply referenced to the switch node.

- **Bootstrap topology**: a diode + capacitor per half-bridge. When the low-side switch is on (switch node near ground), the bootstrap capacitor charges through the bootstrap diode from a fixed low-voltage rail (e.g., 12–15 V gate-drive supply) up to that supply voltage. When the high-side switch turns on, the switch node rises to the bus voltage, and the bootstrap capacitor (now floating, charged) supplies the high-side gate driver referenced to the elevated switch node.
- **Bootstrap capacitor sizing**: must supply the high-side gate charge (Qg from the FET datasheet) each switching cycle, plus driver quiescent current, while its voltage droop stays within the gate driver's minimum UVLO threshold — rule of thumb: Cboot ≥ 10–20x the total gate charge required per cycle divided by the allowed droop voltage; commonly 100 nF–1 µF ceramic X7R, placed immediately across the bootstrap diode's output and the switch-node/high-side-return pins of the driver IC.
- **Bootstrap refresh limitation**: the bootstrap capacitor only recharges while the low-side switch is on (pulling switch node to ground) — at very high duty cycle (high-side on almost continuously) or very low switching frequency, the bootstrap cap doesn't get enough refresh time and can droop below UVLO, causing the high-side gate drive to fail. This is a real limitation for BLDC/FOC at low electrical frequency or near 100% duty — some driver ICs include a "bootstrap refresh" scheme or a charge-pump alternative for these cases; check the driver IC's application note for max recommended duty cycle/minimum switching frequency with bootstrap supply.
- **Isolated/floating gate drive supplies** (isolated DC-DC per high-side gate, or a dedicated isolated gate-driver IC) avoid the bootstrap refresh limitation entirely and are used in high-power or 100%-duty-capable designs, at higher cost/complexity.
- Bootstrap diode should be a fast-recovery type rated for the full bus voltage, since it blocks the switch-node voltage when the high side is on.

## Dead time

Dead time is the deliberate delay between turning off one switch in a half-bridge and turning on the complementary switch, preventing **shoot-through** (both switches briefly conducting simultaneously, which creates a near-short across the bus and can destroy both switches).

- Dead time must exceed the slower switch's total turn-off delay + fall time, with margin — typical values range from tens of ns (fast, low-voltage GaN/small MOSFETs) to several hundred ns (larger MOSFETs/IGBTs, higher voltage).
- Most gate driver ICs with integrated dead-time generation let you set it via a resistor or register; too little dead time risks shoot-through, too much dead time increases distorted output voltage/current (dead-time distortion), reduces achievable duty cycle range, and adds low-order harmonic distortion in FOC current control — tune to the minimum safe value for the specific switches used, not an arbitrarily large margin.
- Verify dead time on the bench with a scope across the switch-node voltage/gate signals under real load conditions (parasitic ringing and gate drive loop inductance affect actual switching speed beyond datasheet typical numbers) before finalizing firmware dead-time settings.

## Shunt current sensing for motor drives

- **Single shunt (DC-link) sensing**: one shunt in the inverter's DC return path, current reconstructed from PWM switching pattern sampling at specific points in the PWM cycle — lowest cost, but requires careful ADC sample timing (only certain PWM states allow valid phase current reconstruction) and has limitations at low modulation index/near-zero-vector conditions.
- **Two or three-shunt (per-phase, low-side) sensing**: a shunt in each (or two of three) low-side switch return paths, sampled while the corresponding low-side switch is on — more robust reconstruction across the full modulation range, standard for FOC drives needing accurate current control across all operating points.
- **In-line (high-side of phase) sensing** with isolated amplifiers: used when common-mode voltage or isolation requirements prevent low-side sensing referenced to a shared ground.
- All shunt current sensing needs **Kelvin (4-wire) connection** and a differential/isolated amplifier with adequate common-mode rejection and bandwidth for the PWM switching frequency — see power_high_current_and_thermal.md for Kelvin layout rules.
- Shunt value selection: low enough to minimize power loss (P = I²×R) and voltage burden, high enough that the sense signal is well above amplifier offset/noise floor — typical motor-phase shunts range from a fraction of a mΩ (high current drives) to several mΩ or tens of mΩ (lower current drives).
- Sample-and-hold/blanking time after each PWM switching transition is required before sampling shunt current, to avoid capturing switching-transient ringing — follow the specific gate driver/current-sense amplifier's recommended blanking time.

## Encoder and position sensor interfaces

- **Incremental encoders (quadrature A/B, plus optional Z index)**: provide relative position/speed, typically require a dedicated quadrature decoder (in MCU peripheral or discrete logic) — route A/B/Z as a matched-length differential pair set if using differential (RS-422-style) encoder outputs, with termination per the encoder's output driver type.
- **Absolute encoders (SSI, BiSS-C, or similar serial protocols)**: provide absolute position on power-up without homing — common in robotics joints where losing position reference is unacceptable. These are serial/synchronous interfaces requiring careful clock/data timing and often need isolation or careful grounding if the encoder is mounted on a moving, remotely-grounded part of the mechanism.
- **Resolvers**: analog, transformer-based, rugged (no active electronics at the sensor), common in harsh-environment/high-temperature motor applications, requires a resolver-to-digital converter (RDC) IC or MCU peripheral with excitation drive and demodulation.
- **Hall sensors (for BLDC commutation, not precision position)**: 3 digital Hall outputs spaced 120° electrical apart, giving 6-step commutation timing — simple, low resolution, adequate for trapezoidal BLDC but not for smooth FOC (FOC needs continuous angle, from a true encoder/resolver or a sensorless observer).
- Route encoder/position-sensor signal wiring away from motor phase wiring and switch-node copper — these are low-level, often high-impedance signals highly susceptible to the motor drive's own switching noise; use shielded cable for the encoder run where phase currents are significant, and terminate shield at one end (or per the encoder manufacturer's grounding guidance) to avoid ground loops.

## Conveyor belts, elevators, and functional safety context

- **Conveyor drives**: typically standard AC induction or BLDC/PMSM drives with variable-frequency control; safety considerations center on emergency-stop circuits (hardwired E-stop interrupting motor power independent of the control firmware — never rely on software-only stop for an E-stop function), guarding interlocks, and overcurrent/stall protection to prevent motor damage or fire on jam conditions.
- **Elevators**: subject to stringent safety-lift standards (e.g., EN 81-20/50 in Europe, ASME A17.1 in North America) covering redundant braking, overspeed governors, and safety circuits — at a principles level (this guide does not substitute for the full standard): elevator drive systems require **dual/redundant brake control** (two independent electromechanical brakes or a brake plus an independent electronic torque-limiting/stop function, so a single point of failure in one brake channel doesn't result in an uncontrolled car), **independent overspeed detection** (separate from the normal drive's speed feedback, triggering mechanical safety gear if exceeded), and safety circuits implemented with certified safety relays or safety-rated PLCs (not general-purpose microcontroller logic) for any function whose failure could cause a fall or entrapment hazard. Any board contributing to elevator safety functions needs to be designed against the applicable functional-safety requirements (e.g., relevant IEC 61508/EN ISO 13849 performance-level analysis) from the start of the architecture, not retrofitted — this is a systems/architecture decision more than a component-selection one, and typically requires specialist safety-certification review beyond general PCB design practice.
- General principle for any safety-relevant motion system: separate the safety function (E-stop, overspeed cutoff, brake control) electrically and logically from the performance/control function, so a bug or fault in motion-control firmware cannot defeat the safety function.

## Robotics and humanoid actuator boards

- **FOC drivers for compact/high-density actuators**: modern robotics joints increasingly integrate the 3-phase inverter, current sensing, gate drivers, and often the FOC control MCU directly into a compact board mounted at or very near the joint — this drives tight thermal and EMI-dense design: place the inverter's hot loop (bus capacitor to switches to phase output) with minimal loop area per motor_drives, and budget thermal vias/copper aggressively since these boards often have very limited surface area for heatsinking (see power_high_current_and_thermal.md).
- **CAN-FD or EtherCAT daisy-chaining for multi-joint communication**: humanoid/multi-axis robots commonly chain many actuator boards on a single communication bus for synchronized, low-latency motion control. CAN-FD (higher data rate than classic CAN, up to 5–8 Mbps typical in these applications) is common for cost-sensitive/moderate-node-count designs; EtherCAT is common where hard real-time determinism and larger data payloads (e.g., streaming torque/position/current telemetry from many joints) are needed — EtherCAT's daisy-chain architecture (each node has 2 PHY ports, processes frames on-the-fly) fits naturally with a chain of joint boards. See industrial_plc_io.md for EtherCAT PHY basics.
- **Thermal density**: actuator boards packed into small joint housings with the motor itself as a nearby heat source face compounded thermal stress — worst-case thermal analysis must include heat conducted from the motor housing into the board, not just the board's own dissipation; consider thermally isolating mounting (standoffs, thermal breaks) where the motor runs hotter than the board's rated ambient.
- **EMI in dense actuator assemblies**: multiple FOC inverters switching at tens to hundreds of kHz within centimeters of each other (multi-joint assemblies) increases the risk of inter-board EMI coupling — apply hot-loop minimization (motor_drives, power_buck_boost) rigorously, use shielded motor phase cables or twisted phase pairs where practical, and keep low-level encoder/current-sense signal traces on inner layers or shielded away from adjacent joint boards' switch nodes.

## EMI considerations specific to motor drives

- Motor phase outputs are high-dv/dt, high-di/dt nodes (PWM-switched, often tens to hundreds of volts at tens to hundreds of kHz effective edge rate) — treat phase output copper and cabling as a radiating source: keep phase traces/cables away from sensitive analog and communication wiring, and consider a common-mode choke on the phase output cable bundle for conducted/radiated emissions compliance (many motor drives fail CISPR 32/11-class conducted emissions specifically from phase-cable common-mode current without this).
- Motor windings' parasitic capacitance to a grounded motor frame, combined with fast dv/dt phase switching, drives common-mode current through motor bearings and back through the system ground — this can cause bearing pitting/failure over time in poorly filtered drives (a known long-term reliability issue in VFD-driven induction motors) and is mitigated by common-mode chokes, slower edge rates (where performance allows), or shielded motor cable with a low-impedance shield ground return.
- See protection_emc_esd.md for general EMC layout principles (return paths, stitching, shielding) that apply directly to motor drive boards.

## Worked example: bootstrap capacitor sizing

A half-bridge drives a high-side MOSFET with total gate charge Qg = 40 nC at the chosen gate-drive voltage, switching at fsw = 20 kHz, gate driver quiescent current on the high side ≈ 100 µA, and the design allows a maximum bootstrap capacitor voltage droop of 0.3 V per cycle (gate driver UVLO margin permits this).

1. Charge consumed per switching cycle: Q_per_cycle = Qg + (Iq_high_side / fsw) = 40 nC + (100 µA / 20,000 Hz) = 40 nC + 5 nC = 45 nC.
2. Minimum bootstrap capacitance for the allowed droop: Cboot(min) = Q_per_cycle / ΔV = 45 nC / 0.3 V = 150 nF.
3. Apply the common design margin (10–20x is often cited to keep droop small under transient/worst-case duty conditions rather than right at the calculated minimum): Cboot ≈ 150 nF × 10 to 20 ≈ 1.5–3 µF is conservative; many practical designs settle on something in the 1–2.2 µF X7R ceramic range for a gate charge this size, verified against the driver IC's own application note recommendation.
4. Check refresh time: at fsw = 20 kHz (50 µs period) and a reasonable minimum low-side on-time (depends on modulation, but even 10% low-side duty at this frequency gives 5 µs refresh time per cycle) — plenty of time to recharge a 1–2 µF cap through the bootstrap diode from the 12–15 V gate supply rail; if this were instead a very low switching frequency (e.g., a few hundred Hz, common at low electrical speed in BLDC/FOC) or very high duty cycle (>95% high-side on-time), refresh time could become marginal and would need explicit verification against the driver's minimum refresh-time spec, or a bootstrap-refresh/charge-pump scheme instead.

This calculation should be redone for every new gate charge/frequency/duty combination — a bootstrap cap value copied from a different design's reference schematic may be badly undersized or oversized for a different switching frequency or FET.

## Common mistakes

- Sizing the bootstrap capacitor without checking gate charge requirements and refresh-time limitations at the drive's actual duty cycle/frequency range.
- Setting dead time by copying a value from an unrelated design instead of verifying against the actual switch's turn-off characteristics and bench measurement.
- Using single-shunt DC-link current sensing in an application requiring accurate current control near zero speed/low modulation index, where single-shunt reconstruction is unreliable.
- Routing encoder/position sensor wiring parallel to motor phase cabling, picking up switching noise that corrupts position feedback.
- Treating a software/firmware stop as sufficient for an E-stop or safety-critical braking function instead of a hardwired, independent safety circuit.
- Underestimating thermal load in compact robotic actuator boards by ignoring heat conducted in from the adjacent motor housing.
- Omitting common-mode filtering on motor phase cabling, causing EMC test failures or long-term bearing damage from common-mode current.
- Using 2-wire (non-Kelvin) shunt connections in a current-sense path meant for closed-loop FOC control, corrupting the control loop's current feedback accuracy.

## Schematic review checklist

- [ ] Gate driver topology (bootstrap vs isolated supply) matched to the application's duty-cycle/frequency range, with bootstrap capacitor sized for gate charge and refresh timing.
- [ ] Dead time setting justified against the specific switch's turn-off characteristics, not copied from an unrelated design.
- [ ] Current-sense topology (single-shunt, multi-shunt, or in-line isolated) matched to the control accuracy/modulation-range requirement.
- [ ] Flyback/freewheeling paths and snubbers present on all switched inductive elements (motor windings, relay coils in associated control circuits).
- [ ] Encoder/position sensor interface type identified (incremental, absolute, resolver, Hall) with appropriate decode/interface circuitry.
- [ ] Safety-critical stop/brake functions implemented via independent, hardwired paths, not solely through control firmware.
- [ ] CAN-FD/EtherCAT or other multi-node communication interface specified with correct termination and PHY/isolation per industrial_plc_io.md.

## Layout review checklist

- [ ] Inverter hot loop (bus capacitor–switches–phase output) minimized in area, matching power_buck_boost_converters.md hot-loop principles.
- [ ] Bootstrap capacitor placed immediately across the driver's bootstrap/switch-node pins with short traces.
- [ ] Shunt current-sense traces are 4-wire Kelvin, routed as tight differential pairs away from phase/switch-node copper.
- [ ] Encoder/position sensor traces routed away from phase output copper and switching nodes, shielded/twisted where the run is long or noisy.
- [ ] Common-mode choke or filtering present on motor phase cable exit if EMC compliance requires it.
- [ ] Thermal vias and copper area sized for worst-case inverter dissipation, accounting for any adjacent motor-housing heat in compact actuator designs.
- [ ] Paralleled switches (if used for higher current) laid out symmetrically per power_high_current_and_thermal.md.
- [ ] Safety-circuit wiring/traces (E-stop, brake control) kept physically and electrically separate from general control logic routing.
