---
title: Conveyor and Motion Controller Reference Architecture
domain: industrial
tags: [conveyor, vfd, servo, encoder, photo-eye, e-stop, iso 13849, motion control, jam detection]
applies_to: [conveyor control boards, motion controller boards, material handling controllers]
---

## System overview

A conveyor/motion controller sits between a supervisory PLC (or standalone logic) and one or more motor drives (VFD for induction-motor conveyor sections, servo drives for precision-indexed or synchronized axes), reading sensors (photo-eyes, encoders, load cells) and enforcing safety stop functions. Architecture splits into: motion/drive interface, sensor interface, safety/e-stop chain, and supervisory communication.

## Power tree

- Conveyor sections: 3-phase 208/230/400/480 VAC (region-dependent) feeding VFDs directly from the building/machine supply — see motor_drives_and_motion.md for VFD internal power-stage principles.
- Control electronics: 24 VDC control power from a DIN-rail supply, dropped to 5 V/3.3 V for MCU logic via buck converters; typical draw for a multi-axis motion controller board is 0.5–2 A at 24 V depending on I/O count and driven sensors (photo-eyes often draw 20–100 mA each at 24 V).
- Sensor excitation: photo-eyes, proximity sensors, and encoders are usually powered from the same 24 VDC field rail, individually fused or current-limited per channel/group to prevent one shorted sensor cable from taking down an entire conveyor zone's sensing.
- E-stop and safety relay coils: powered from a rail that is itself gated by upstream e-stop contacts in a fail-safe (de-energize-to-stop) architecture — never power a safety relay coil from a rail that stays live regardless of e-stop state and rely on logic alone to command it off.

## Key part families

- **VFDs**: general-purpose industrial VFD families (e.g., ABB ACS-class, Siemens SINAMICS, Yaskawa) driven by analog reference or fieldbus, sized to the conveyor motor's rated power.
- **Servo drives**: EtherCAT/CANopen (CiA 402) servo drives (e.g., Beckhoff AX5000-class, Kollmorgen, Yaskawa Sigma-class) for indexed/synchronized axes.
- **Photo-eyes/proximity sensors**: through-beam and retroreflective photoelectric sensors (e.g., Banner, Sick, Omron) with NPN/PNP 24 V outputs.
- **Load cells and weigh ADC**: strain-gauge load cells paired with a dedicated weigh-scale ADC IC (e.g., TI ADS1230-class, HX711-class for lower-precision applications).
- **Safety relays/light curtains**: certified safety relay modules and optical safety light curtains (e.g., Sick, Pilz, Banner) for guarded pinch points.
- **STO-capable drives**: modern servo/VFD families with an IEC 61800-5-2 certified Safe Torque Off input, avoiding a separate external contactor per axis.

## Drive interface: VFD and servo

- **VFD interface (induction motor conveyor sections)**: typically a 0–10 V or 4-20 mA speed reference plus digital run/direction/fault I/O, or a fieldbus link (Modbus RTU, PROFIBUS, EtherNet/IP) for full parameter/status access — see industrial_plc_io.md for analog/fieldbus interface principles. VFD fault output should be wired back as a digital input the controller actively monitors, not polled only occasionally.
- **Servo interface (precision-indexed or synchronized axes)**: increasingly EtherCAT or CANopen (CiA 402 profile) for tightly synchronized multi-axis motion (e.g., sorting conveyors, pick-and-place transfer sections) — see plc_controller_and_io_modules.md and motor_drives_and_motion.md for EtherCAT/CAN-FD electrical basics. Servo drives handle their own current/FOC loop internally; the motion controller sends position/velocity/torque commands and reads status over the fieldbus rather than driving the motor directly.
- **Local FOC/BLDC driver (compact/integrated designs)**: smaller conveyor zones or robotic transfer axes sometimes integrate the motor driver directly on the controller board rather than using an external drive — in that case follow motor_drives_and_motion.md's gate driver, dead-time, and shunt-sensing guidance directly.

## Sensor interface

- **Photo-eyes (through-beam or retroreflective)**: typically NPN or PNP 24 V digital outputs, sometimes with a separate "dark-on/light-on" configuration — treat exactly like any 24 V digital input per industrial_plc_io.md (series impedance, filtering, isolation). Debounce carefully: a photo-eye at a belt-speed-dependent detection point may generate rapid transitions from a marginal/edge-of-beam object, and excessive debounce delay can miscount fast-moving small items — tune debounce time against actual belt speed and minimum object size, not a generic default.
- **Encoders for belt speed/position tracking**: incremental quadrature encoder on a drive roller or idler roller gives belt linear position/speed reference used for zone-to-zone timing, jam detection (commanded speed vs. actual encoder-derived speed mismatch), and sometimes print/label registration. Route per motor_drives_and_motion.md encoder guidance — keep away from VFD output cabling.
- **Load cells / weight sensors** (checkweighing, scale conveyors): low-level differential mV/V output requiring a precision instrumentation amplifier and often a dedicated weigh-scale ADC IC (24-bit sigma-delta) — treat as a precision analog front end per power_decoupling_and_pdn.md and analog_and_mixed_signal.md; keep excitation and sense wiring as a proper 4-wire (or 6-wire) Kelvin connection to the load cell per the cell's datasheet.
- **Jam/stall detection**: implemented either via encoder-vs-commanded-speed mismatch, VFD/servo overcurrent fault reporting, or a dedicated mechanical slip-clutch/torque-limiter with a position switch — a robust design uses at least two independent indicators (e.g., encoder mismatch AND drive overcurrent) rather than relying on a single detection method, since a jam's electrical signature varies with what's jammed.

## Safety architecture (ISO 13849 / IEC 62061 principles)

- **E-stop circuit**: hardwired, normally-closed pushbutton(s) in series, feeding a certified safety relay or safety-rated PLC input — never route the sole e-stop function through the general motion-control MCU's GPIO with only a software response, per the same principle as motor_drives_and_motion.md's E-stop guidance.
- **Category and Performance Level selection (ISO 13849-1 framework, conceptually)**: the required Performance Level (PLa–PLe) for a given safety function depends on severity of possible injury, frequency/duration of exposure, and possibility of avoiding the hazard — a simple low-speed conveyor's pinch-point guard interlock might only need a lower PL/Category (e.g., Category 1 single-channel with well-tested components), while a conveyor with significant crush/entanglement hazard and frequent operator proximity typically needs a higher PL (dual-channel, cross-monitored architecture, Category 3 or 4) — this determination is a systems-safety analysis task, not a PCB design choice, and should be done by/reviewed with a functional-safety-competent engineer before the electrical architecture is finalized.
- **Dual-channel safety switches**: where higher PL is required, safety-rated guard-door switches and e-stops provide two independent normally-closed contacts, both wired into a safety relay/module that cross-monitors them (detects a discrepancy between the two channels as itself a fault condition) — this catches a single failed contact that a single-channel design would miss.
- **Light curtains / safety mats at pinch points and transfer zones**: an independent optical or pressure-sensitive detection zone that, like the e-stop chain, interrupts drive power through a safety relay rather than through general logic.
- **Safe torque off (STO) on modern servo/VFD drives**: many current-generation drives include a certified STO input (a safety function built into the drive itself, IEC 61800-5-2) that removes torque-producing capability without removing all power to the drive electronics — using a drive's STO input wired from the safety chain is now a common, drive-vendor-supported way to achieve safety-rated stop without a full external contactor for every axis; verify the specific drive's STO certification (PL/SIL rating) matches the application's required level.

## Layer count and stackup

- Multi-axis motion controller board: 4–6 layers typical — a dedicated ground plane and careful separation of encoder/analog sensing from any onboard motor-drive switching stage (if integrated) per motor_drives_and_motion.md.
- Simple single-zone conveyor I/O board (VFD interface + a handful of photo-eyes, no integrated drive): 4 layers is standard practice, matching industrial_plc_io.md I/O module guidance.

## Placement and routing priorities

1. Safety-relay/e-stop circuitry grouped and visually separated from general I/O, mirroring elevator_controller.md's safety-chain zoning principle.
2. Encoder and load-cell analog/low-level signal traces routed away from VFD/servo power interface connectors and any onboard switching converter.
3. Photo-eye and sensor field terminals grouped with clear silkscreen labeling (which zone, NPN/PNP type) to reduce field commissioning errors across a conveyor line with many similar-looking terminal blocks.
4. Fieldbus (EtherCAT/CAN) connectors positioned for the physical daisy-chain routing along the conveyor's mechanical layout, with in/out labeling matching the intended cable run direction.
5. STO or safety-relay outputs to each drive kept as short, direct runs to the drive's safety input connector, not routed through a shared connector with non-safety signals.

## Standards references (principles only)

- ISO 13849-1/2 — safety of machinery, performance-level-based design of safety-related control systems (the framework referenced above for e-stop/guard circuit category selection).
- IEC 62061 — alternative SIL-based framework for safety-related control systems of machinery, often used interchangeably with ISO 13849 depending on industry/region convention.
- IEC 61800-5-2 — safety functions (including STO) for adjustable-speed electrical power drive systems.
- Machinery Directive (EU) / OSHA machine-guarding requirements (US) — overarching regulatory context driving the above standards' application.

## Test and bring-up plan

1. Bench-verify e-stop and safety-relay logic standalone (simulated switch inputs) before connecting to real drive power, same principle as elevator_controller.md.
2. Bring up VFD/servo drives individually with the conveyor mechanically decoupled or run at very low speed first, verifying direction, speed reference scaling, and fault reporting.
3. Verify encoder-derived speed tracking against a known reference (hand-turned roller or low, controlled belt speed) before relying on it for jam detection thresholds.
4. Test each photo-eye/sensor channel with an actual object at realistic belt speed, checking for missed detections or double-triggers before tuning debounce values.
5. Perform e-stop function test at running speed (not just standstill) to verify actual stopping distance/time meets the safety analysis's assumed stopping performance — this connects the electrical safety-relay test to the mechanical/systems-level safety requirement.
6. Fault injection: disconnect an encoder cable mid-run and verify jam/fault detection responds appropriately rather than the system continuing to command speed based on a stale or zero reading without flagging a fault.

## Common failure modes

- Photo-eye debounce tuned generically rather than against actual belt speed and minimum object size, causing missed or double counts.
- Jam detection relying on a single indicator (e.g., only VFD overcurrent) that doesn't trigger for jams whose electrical signature stays within normal current range (e.g., a low-friction jam that stalls the encoder without much current rise).
- E-stop or guard-interlock wired through the general motion controller's software logic instead of a hardwired safety relay/certified safety PLC.
- STO input used on a drive without verifying its certified PL/SIL rating actually meets the application's determined safety requirement.
- Encoder or load-cell signal cabling routed alongside VFD output power cabling, corrupting speed/weight readings with switching noise.
- Safety-relay coil powered from a rail that remains live independent of the e-stop chain, defeating the fail-safe de-energize-to-stop principle.

## Schematic review checklist

- [ ] E-stop and guard-interlock circuits are hardwired through certified safety relays/safety PLC, independent of general motion-control MCU logic.
- [ ] Required Performance Level/Category for each safety function has been determined (by a competent safety engineer) and the circuit architecture (single vs. dual-channel, cross-monitoring) matches it.
- [ ] STO or equivalent drive safety input used only where its certified rating meets the application's required PL/SIL.
- [ ] Jam/stall detection uses at least two independent indicators where practical (encoder mismatch, drive fault, mechanical torque limiter).
- [ ] Load cell/weigh sensor interface uses proper Kelvin excitation/sense wiring and a precision ADC front end.
- [ ] VFD/servo fault outputs wired back as monitored digital inputs, not left unconnected.

## Layout review checklist

- [ ] Safety-relay/e-stop circuitry zoned separately from general I/O and drive-interface circuitry.
- [ ] Encoder and load-cell signal traces routed away from VFD/servo power connectors and any onboard switching converter's hot loop.
- [ ] Sensor/field terminals clearly labeled by zone and type (NPN/PNP) on silkscreen.
- [ ] Safety-relay/STO output wiring to each drive kept direct and separate from non-safety signal connectors.
- [ ] Fieldbus daisy-chain connector in/out orientation matches intended physical cable routing along the conveyor.
