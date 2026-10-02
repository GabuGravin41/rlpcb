---
title: Elevator Controller Reference Architecture
domain: industrial
tags: [elevator, safety chain, en 81-20, en 81-50, door operator, vfd, brake control, redundancy, safety relay]
applies_to: [elevator control boards, lift controller boards, door operator boards, safety circuit boards]
---

## Scope and standards context

This guide describes electrical architecture principles common to elevator/lift controllers at a conceptual level, referencing standards by name (EN 81-20 mechanical/electrical safety requirements for passenger and goods lifts, EN 81-50 examination and test requirements for lift components, ASME A17.1 in North America) without reproducing their normative text. A real elevator controller design must be reviewed against the full current standard text and typically requires third-party certification (notified body review in the EU) — treat this guide as architecture orientation, not a compliance substitute.

## System overview: the three control domains

An elevator controller separates into three largely independent electrical domains, deliberately kept from sharing single points of failure:

1. **Safety chain** — a hardwired series loop of safety contacts (door locks, final limit switches, overspeed governor contact, pit/headroom stop switches, buffer switches, safety-gear switches) that directly interrupts power to the drive/brake when open. This is the domain where EN 81-20 places the strictest requirements.
2. **Motion/drive control** — the VFD (variable frequency drive) or dedicated elevator drive, brake control, and the general logic controller (car calls, floor selection, door timing) that decides when and how the car should move.
3. **Communication/dispatch** — car/hall call registration, floor indicators, intercom, and (in group-controlled installations) dispatcher communication between multiple cars — non-safety-relevant but operationally essential.

## Key part families

- **Safety relays/modules**: force-guided (positively-guided) contact relays and certified safety-monitoring modules (e.g., Pilz PNOZ-class, Schneider Preventa-class, Siemens SIRIUS safety relay families) for the safety-chain cutoff and contactor-monitoring function.
- **Contactors**: mechanically-latching or standard AC/DC motor contactors rated for the drive's full-load and locked-rotor current, used in the redundant dual-contactor motor-power path.
- **Drive/VFD**: purpose-built elevator drives or heavily configured industrial VFDs (e.g., KEB, Fuji, Yaskawa elevator-rated drive families) with regenerative front-end or braking-chopper options.
- **Brake driver**: high-current low-side or H-bridge driver ICs/discrete stages for the electromagnetic brake coil, with PWM or two-stage voltage-drop holding-current control.
- **Door operator motor**: small BLDC/PMSM with an integrated or companion FOC driver, following motor_drives_and_motion.md.
- **Safety-rated sensors**: door interlock switches, overspeed governor switches, and light-curtain/safety-edge modules from safety-component vendors (e.g., Fortress, Pilz, Sick) carrying the relevant safety-contact certification.

## Safety chain architecture

- The safety chain is a **series-wired loop**: every safety-relevant contact (normally-closed) is wired in series so that any single open contact anywhere in the building interrupts the loop. The loop typically runs at a low DC voltage (commonly 24 VDC in modern controllers, though older installations use mains-referenced circuits) through relay coils that, when de-energized, remove power from the drive and apply the brake.
- **Safety relays, not general logic**: the contactors/relays that physically remove drive power and set the brake are certified safety relays (positively-guided/force-guided contact relays) or a certified safety PLC (SIL/PL-rated), not the general-purpose motion controller MCU. The motion controller MCU may *monitor* the safety chain state (for diagnostics/logging) but must never be the sole element capable of *overriding* it.
- **Redundant contactor architecture**: EN 81-20 requires two independent contactors (or an equivalent electronic means with diagnostic coverage) in series in the motor power path, each individually capable of removing power, with a monitoring circuit that detects if either contactor fails to open (welded-contact detection) and prevents the next start command if a fault is detected — this is the classic "two contactors + contactor-monitoring" architecture found in virtually every modern traction/hydraulic elevator drive cabinet.
- **Door lock/interlock monitoring**: each landing door and the car door has an electrical interlock contact wired into the safety chain, confirming the door is both closed and mechanically locked before the chain permits motion — a door "closed" sensor and a door "locked" sensor are often separate contacts (closed ≠ locked) and both should be verified independently where the standard requires it.
- **Overspeed governor**: an independent mechanical (centrifugal) or electronic speed-sensing device, separate from the drive's own speed feedback loop, that trips a safety-gear mechanism and opens a safety-chain contact if car speed exceeds a threshold — this independence is the core redundancy principle: the normal drive's speed control must not be the only thing standing between normal operation and an overspeed condition.

## Brake control architecture

- **Dual independent brake channels**: modern elevator controllers drive the electromechanical brake (typically a spring-applied, electromagnetically-released brake — fails safe to "applied/braking" on power loss) through two independent control paths (e.g., two separate power transistors/relays in series feeding the brake coil, each individually capable of interrupting brake-release current), so a single shorted switch doesn't leave the brake permanently released.
- **Brake coil driver**: the brake solenoid is a significant inductive load (its coil current can be several amps depending on brake size) — driver stage needs a flyback/freewheeling path sized for the coil's stored energy and a controlled-release scheme (many modern controllers use PWM or a two-stage voltage drop — full voltage to lift the brake, then a reduced holding voltage — to reduce coil heating and mechanical wear/noise during extended hold periods).
- **Brake torque/state confirmation**: many current designs monitor brake pad position or lift-arm switches to confirm the brake has actually physically lifted before commanding motor torque, and confirm it has actually reseated after a stop — an "I sent the release command" signal is not equivalent to "the brake is confirmed open," and standards increasingly expect the latter.
- **UCM (Unintended Car Movement) protection**: EN 81-20 requires detection and arrest of car movement with doors open when not intentionally commanded — typically implemented as an independent monitoring function (separate from the main motion controller) that can apply the brake or otherwise stop the car if car movement is detected while a door-open condition exists.

## VFD/drive interface

- The elevator drive itself is usually a purpose-built or heavily configured industrial VFD (see motor_drives_and_motion.md for general VFD/motor-drive electrical principles) commanded by the elevator controller over a fast deterministic link (analog velocity reference plus digital enable/direction, or increasingly a fieldbus such as CANopen or a vendor-proprietary serial link for full digital control including torque/position feedback).
- **Drive enable is gated through the safety chain**, not just a controller command — the drive's enable input should be wired so the safety-chain relays physically remove its ability to output torque, independent of what the drive's own firmware is doing.
- Speed/position feedback for closed-loop control comes from an encoder on the motor or governor sheave; this feedback is separate from (and should not be assumed equivalent to) the independent overspeed governor's own sensing.
- Regenerative energy: elevators regularly regenerate power (descending loaded car, ascending empty car) — drive architecture needs either a braking resistor/chopper stage or (increasingly common in modern installations for energy recovery) a regenerative front-end that feeds energy back to the building supply; either way, size the braking resistor/chopper for worst-case regenerative duty cycle, not just occasional braking events.

## Door operator architecture

- Door operator is its own motor-drive subsystem (small BLDC or PMSM typically, see motor_drives_and_motion.md) controlling door open/close motion with force-limiting — standards require the door to stop/reverse on encountering an obstruction, implemented via current/torque sensing on the door motor (detecting the current spike from mechanical resistance) combined with, in many designs, a physical safety edge or light curtain sensor providing an independent obstruction-detection path.
- Door lock/interlock hardware (electromechanical, not just a sensed state) must be independently verified by the safety chain as described above — the door operator's own motor controller closing the door does not by itself satisfy the interlock requirement.
- Light curtain / safety edge sensor interface: an infrared light-curtain array or a mechanical safety edge along the door's leading edge provides obstruction detection independent of motor current sensing — treat this as a required redundant channel for door-closing safety, not an optional convenience feature, per current standard practice.

## Power tree

- Building supply (typically 3-phase 380–480 VAC in commercial installations) feeds the VFD's rectifier/DC bus directly (see motor_drives_and_motion.md and power_high_current_and_thermal.md for high-current AC/DC-bus design).
- Control logic power: a compact AC/DC or isolated DC/DC supply drops to 24 VDC for the safety chain and general control logic, further regulated to 5 V/3.3 V for MCU-level electronics — this control power supply should be backed by a small UPS or capacitor-hold-up circuit sufficient to complete a controlled stop/door-open sequence on mains loss, not just log the fault.
- Car-top and car-top-to-controller wiring: a traveling cable carries safety-chain conductors, door operator power/signal, car lighting, and communication between the car and the machine-room/controller — traveling cable conductor count and shielding should be planned early since it constrains available signal types (twisted/shielded pairs for communication, dedicated conductors for safety-chain contacts that must not share a conductor with anything else).

## Layer count and stackup

- Main controller board: 6–8 layers typical, separating safety-chain logic (dedicated layer/zone), motor-drive control signals, and general logic/communication — physical/layout separation between safety-chain circuitry and general logic is a review point auditors look for even though the standard doesn't dictate PCB stackup directly.
- Safety-relay interface boards (if separate from the main controller) can often be simpler 4-layer boards given the safety relays themselves do the heavy switching.

## Placement and routing priorities

1. Safety-chain relay coils, contactor-monitoring circuitry, and the safety-chain input/output terminals grouped in a clearly demarcated board zone, ideally with silkscreen/board-outline visual separation from general logic.
2. Dual/redundant contactor drive circuits laid out symmetrically with independent PCB traces (not a shared trace split late) from the safety relay output to each contactor coil, so a single trace/via defect can't disable both channels.
3. Brake driver's flyback/freewheeling components placed immediately at the brake coil driver output, sized for the coil's inductive energy.
4. High-current motor/drive power paths kept away from and, where they must cross, orthogonal to low-level safety-chain sensing and encoder signal traces.
5. Traveling-cable and hall-call wiring terminal blocks clearly labeled and grouped by function (safety, power, communication) to reduce field-wiring error risk during installation and service.

## Safety and standards references (principles only)

- EN 81-20 (safety rules for construction/installation of lifts) and EN 81-50 (examination/test of components) — structural, mechanical, and electrical safety requirements including safety chain, brake redundancy, UCM protection, door protection.
- ASME A17.1/CSA B44 — North American equivalent safety code.
- IEC 61508 / ISO 13849 — functional safety framework often referenced for the electronic safety-related parts of the control system (Safety Integrity Level / Performance Level determination for safety functions like UCM detection, door protection, overspeed).
- Any board performing a safety function in a real installation requires review/certification appropriate to the jurisdiction — this guide supports architecture-level understanding, not a certification pathway.

## Test and bring-up plan

1. Bench-test the safety-chain relay/contactor-monitoring logic standalone with simulated contact inputs (switches) before connecting to any real motor power — verify every single simulated open-contact condition correctly removes drive enable and applies brake.
2. Verify dual-contactor welded-contact detection by manually holding one contactor closed (simulating a weld) and confirming the system detects the fault and inhibits the next start.
3. Bring up the drive/VFD on a dynamometer or with the motor mechanically decoupled from the actual car/counterweight system first, verifying speed control and brake-release/reseat timing in isolation.
4. Verify UCM detection function with the car stationary, doors open, by injecting a simulated small movement (encoder pulses) and confirming the independent monitor commands a stop within the expected reaction time.
5. Full system commissioning under supervision of the applicable certification body/inspector per local elevator code — this step is a regulatory requirement, not optional bring-up practice.
6. Long-term: periodic (per code-mandated interval) test of governor overspeed trip, buffer function, and safety-gear engagement as part of ongoing maintenance, not just initial commissioning.

## Common failure modes

- Safety-chain contact wired through a connector or terminal shared with a non-safety signal, creating an unintended common failure point.
- Contactor-monitoring circuit that only checks "coil was commanded open" rather than actually sensing the contactor's mechanical open state, missing welded-contact faults.
- Brake driver undersized for the coil's actual inrush/holding current, leading to nuisance brake-driver overheating or, worse, marginal brake release under cold/high-friction conditions.
- Door force-limiting relying solely on motor current sensing without an independent light-curtain/safety-edge channel, missing soft/low-resistance obstructions (e.g., a hand at the door edge).
- UCM detection implemented in the same processor/firmware as normal motion control, defeating the independence the function is meant to provide.
- Control-logic power supply with no hold-up capacity, causing an uncontrolled logic reset (and potential unsafe intermediate state) on a brief mains dip.

## Schematic review checklist

- [ ] Safety chain is a single hardwired series loop through certified safety relays/contactors, independent of general MCU logic for the cutoff function itself.
- [ ] Two independent motor-power contactors present with contactor-monitoring (welded-contact detection) before permitting the next start.
- [ ] Brake control has two independent release-interrupt paths and a flyback/freewheeling path sized for the coil's stored energy.
- [ ] Overspeed governor input is a dedicated safety-chain contact, independent of the drive's own speed-feedback loop.
- [ ] Door interlock (locked state) is a dedicated safety-chain contact, separate from any door-closed proximity/limit sensor used for logic only.
- [ ] UCM detection function is architecturally independent (separate monitoring path) from the normal motion controller.
- [ ] Control-logic power has defined hold-up time sufficient for a controlled stop sequence on mains loss.

## Layout review checklist

- [ ] Safety-chain circuitry visually/physically zoned and separated from general logic and motor-drive power routing.
- [ ] Redundant contactor/brake driver traces routed independently from a common source point, not sharing a single trace/via that could defeat redundancy.
- [ ] High-current motor/drive traces separated from and, where crossing, orthogonal to safety-chain and encoder signal traces.
- [ ] Flyback/snubber components for brake coil and other inductive safety-chain loads placed immediately at the driver output.
- [ ] Terminal blocks for traveling cable and hall wiring clearly labeled by function on silkscreen.
