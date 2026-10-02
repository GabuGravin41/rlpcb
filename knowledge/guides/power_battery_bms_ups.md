---
title: Battery Charging, BMS, UPS and Power-Path Design
domain: power
tags: [li-ion, lifepo4, lead-acid, bms, cell balancing, ups, power path, oring, hot-swap, inrush, fusing, busbar]
applies_to: [battery-powered boards, portable devices, industrial UPS, robotics power systems]
---

## Battery chemistries and charging profiles

- **Li-ion (LCO/NMC, 3.0–4.2 V/cell nominal 3.6–3.7 V)**: CC-CV charge — constant current (typically 0.5C–1C, i.e., 0.5–1x the Ah rating) until cell voltage reaches 4.20 V ±0.5%, then constant voltage until charge current tapers to ~0.05C–0.1C ("C/20" or "C/10" termination). Overcharging above 4.25 V risks thermal runaway — voltage accuracy of the charger/BMS is safety-critical, not just a performance spec.
- **LiFePO4 (3.0–3.65 V/cell nominal 3.2 V)**: CC-CV, charge voltage 3.60–3.65 V/cell, much flatter discharge curve than LCO/NMC so state-of-charge estimation from voltage alone is less accurate (needs coulomb counting for good SOC estimates). Inherently more thermally stable than LCO — lower thermal-runaway risk, common in industrial/solar/EV applications.
- **Lead-acid (2.0 V/cell nominal, 12 V = 6 cells)**: CC-CV with a lower float voltage stage afterward — typical flooded/AGM charge: bulk (CC) → absorption (CV ~14.4–14.7 V for 12 V nominal) → float (CV ~13.2–13.8 V for standby/UPS duty). Temperature-compensated charge voltage is standard for lead-acid (~ −3 to −5 mV/°C/cell) because charge voltage requirements shift with temperature — omitting this shortens battery life in temperature-variable environments.
- Always charge within the manufacturer's specified temperature range (commonly 0–45°C for Li-ion charging, charging below 0°C causes lithium plating and permanent capacity loss/safety risk) — a temperature sensor (NTC, often built into the pack) gating charge enable is standard practice, not optional, for Li-ion.

## BMS core functions

A battery management system for multi-cell packs must provide, at minimum:

1. **Cell voltage monitoring**: per-cell voltage measurement (not just pack voltage) to catch individual weak/overcharged cells. Dedicated battery monitor/balancer ICs (multi-channel, e.g., analog front-end parts from TI BQ769x2, Analog Devices LTC68xx, ON/onsemi families) handle this with mV-level accuracy across a stack using level-shifted or isolated measurement architectures.
2. **Overvoltage/undervoltage protection (OVP/UVP)**: cut charge path if any cell exceeds max voltage; cut discharge path if any cell drops below min voltage. Thresholds and response time should be independently verifiable (many designs use a secondary independent protection IC as a redundant safety layer beyond the primary fuel-gauge/BMS IC, following functional-safety practice for battery safety).
3. **Overcurrent/short-circuit protection (OCP/SCP)**: fast-acting cutoff on charge and discharge FETs, typically implemented via comparator thresholds on a current-sense shunt or the FET's Rds(on) voltage drop, with response times from microseconds (hardware comparator) to milliseconds (firmware-based).
4. **Overtemperature protection (OTP)**: NTC thermistor(s) on the cells/pack, gating both charge and discharge.
5. **Cell balancing**: 
   - *Passive balancing*: a bleed resistor + FET per cell shunts excess charge from the highest cell(s) during charging (typically the top-of-charge phase) to equalize the stack. Simple, low cost, wastes energy as heat, balancing current typically tens to ~200 mA per cell.
   - *Active balancing*: transfers charge between cells (capacitor or inductor-based charge shuttling) — higher efficiency, more complex/costly, used in larger packs (EV, grid storage) where balancing losses matter more.
   - Balancing threshold is typically set at a voltage delta between cells (e.g., 20–50 mV) above which balancing engages.
6. **Protection FETs**: back-to-back N-channel MOSFETs in the charge/discharge path (source-to-source or drain-to-drain configuration) allow independent blocking of charge and discharge current directions using the body diodes — standard topology for single-string Li-ion protection. Size FET Rds(on) for acceptable conduction loss (P = I²×Rds(on)) and verify SOA (safe operating area) for worst-case fault current and duration before the protection circuit opens the path.
7. **Fuel gauging (optional but common)**: coulomb counting (current integration) plus voltage/impedance modeling for SOC%, often a separate IC or integrated into the BMS AFE.

## Shunt-based current sensing for BMS

- Use a low-value, low-tempcoefficient shunt resistor (e.g., 0.5–5 mΩ for high-current packs, up to a few tens of mΩ for lower-current packs) in the main current path (often on the low/negative side, referenced to system ground, for simpler single-supply sensing).
- **Kelvin (4-wire) sensing is mandatory**: route separate sense traces from the shunt's current-carrying pads' inner Kelvin sense points to the amplifier/ADC input, not from the same pads carrying load current — otherwise trace/via resistance and connector resistance corrupt the measurement (a few mΩ of extra resistance can be a large percentage error at these shunt values).
- Route Kelvin sense traces as a tightly coupled differential pair, away from high-current traces, to reject common-mode switching noise.
- Choose shunt power rating with margin: P = I²×R at max continuous current, derate to ≤50% of the shunt's rated power for temperature/reliability margin, and account for the shunt's own temperature rise affecting resistance (use low-tempco alloys like manganin/Kelvin-grade shunts for precision current sensing, not generic resistors, when accuracy matters).

## Power-path management and ORing / ideal diodes

Power-path management allows a system to run from either an external supply (charger/adapter) or battery, seamlessly switching, while charging the battery when external power is present — without a hard "either/or" relay.

- **Diode ORing (simple)**: a Schottky diode from each source (battery, external supply) to a common rail; whichever source has the higher voltage naturally supplies the load. Simple and robust, but wastes power as diode forward drop (0.3–0.5 V) × load current, and both sources need enough headroom for that drop.
- **Ideal diode / ORing controller (active)**: a controller IC drives a MOSFET to emulate a diode with near-zero forward drop (drop = I × Rds(on), often <50 mV) — recovers efficiency lost to a real diode, critical in low-voltage-headroom or high-current systems. Used widely in redundant power supplies, hot-swap systems, and battery+adapter power-path ICs.
- **Power-path (charge-while-powering) ICs**: integrate the ORing/switching function with the battery charger, so the system load is powered directly from the input (adapter) when present, and the battery only supplies charge current (not full system current) — reduces battery cycling and charge/discharge losses in "always plugged in with battery backup" designs (laptops, industrial control with battery backup).

## Hot-swap and inrush control

Hot-swap circuits allow a board to be plugged into a live backplane/rail without the inrush current (charging the board's own bulk input capacitance) causing a voltage droop on the shared bus or damaging connector pins/board traces.

- **Inrush current** without control: I_inrush = C_bulk × dV/dt, which for a fast connector-mate transition (effectively a step) can spike to many amps even for modest bulk capacitance — this can trip upstream OCP, cause connector arcing/pitting, or brown out other boards sharing the bus.
- **Hot-swap controller ICs** (e.g., LTC4210/LT4256-style families and equivalents) ramp the input MOSFET gate slowly (controlled dV/dt or controlled current via a sense resistor + control loop) to limit inrush current to a safe programmed level (e.g., limit di/dt or a fixed current ceiling) while the bulk capacitance charges over milliseconds instead of microseconds.
- Include a current-limit/circuit-breaker function in the hot-swap controller (trip and latch off on sustained overcurrent) as standard practice on any board that can be hot-plugged into a shared power bus.
- For simpler/lower-power designs, an NTC inrush-limiting thermistor or a resistor+relay-bypass (charge through resistor, then relay shorts it once capacitor is charged) is a lower-cost alternative to an active hot-swap IC.

## Fusing and protection

- Every battery pack and every board power input should have overcurrent protection appropriate to the fault current available: a fuse, PTC resettable fuse, or electronic fuse (eFuse) sized above normal operating current (with margin, typically 1.25–2x continuous rating per common practice) but below the wiring/PCB trace's damage current.
- **Fuse placement**: as close to the battery/source as possible, in the ungrounded (positive, typically) conductor, so a downstream short is cleared before it can damage wiring back to the source.
- **PTC resettable fuses**: good for lower-current, self-recovering protection (e.g., port protection, low-power rails) but have higher resistance than a fuse and a trip time that's current- and temperature-dependent — not suitable for precise, fast protection of expensive semiconductors.
- **eFuses**: precise current limiting/OCP with fast (µs) response, adjustable trip threshold, and often additional features (reverse-current blocking, inrush limiting, UVLO/OVLO) — increasingly preferred over mechanical fuses in modern designs needing tight, resettable protection.
- Size wire/PCB trace ampacity to exceed the fuse's rating (the fuse should be the weakest link, not the trace) — see power_high_current_and_thermal.md for IPC-2152 trace current sizing.

## UPS / backup battery system principles

- **Topology choice**: offline/standby (switches to battery only on mains failure, fast transfer switch, cheapest, small transfer glitch ~ms) vs line-interactive (regulates voltage without switching to battery for minor sags) vs online/double-conversion (battery/inverter always in the power path, zero transfer time, used where any glitch is unacceptable — e.g., server/industrial control power).
- For small embedded/industrial UPS backup (battery holds up a control board through a brief mains dropout), the standard pattern is: mains-derived DC rail feeds the load and charges the battery through a charge-path diode/controller; the battery connects to the load rail through an ORing diode/ideal-diode so that when mains DC droops below battery voltage, the battery seamlessly takes over — this is the same power-path topology as the section above, just applied at the system (not cell-stack) level.
- Battery sizing: compute required backup time × load current (Ah) = capacity needed, then oversize for battery aging (batteries lose ~20–30% capacity over life before typical replacement threshold) and depth-of-discharge limits (lead-acid: avoid discharging below ~50% DoD for cycle-life reasons; Li-ion: full DoD is more tolerable but still benefits from staying above ~20% for cycle life).
- Include battery disconnect/isolation (relay, FET, or fuse) for long-term storage or shipping to avoid deep-discharge damage from quiescent system draw.

## High-current busbars and copper for battery systems

- For pack-level interconnects and busbars carrying tens to hundreds of amps, PCB copper alone is often insufficient even at 2–6 oz — use solid copper or aluminum busbars bolted/soldered to the board, sized by cross-sectional area for the continuous current with a conservative current density (rule of thumb: 300–500 A/in² conservatively for busbar copper with adequate cooling, but always verify against the specific application's ambient, duty cycle, and connector rating rather than a single fixed number).
- Bolted busbar/lug connections: use appropriate torque (per hardware/connector spec) and star washers or Belleville washers to maintain contact pressure under thermal cycling; undertorqued or corroded high-current joints are a common field-failure and fire-risk point.
- Multiple parallel PCB layers/vias tied together with a busbar landing pad reduce reliance on through-board copper alone for the highest-current segments (e.g., the direct battery-to-fuse-to-main-contactor path).
- Keep sense/control wiring physically separated from busbars and away from their magnetic fields (busbars carrying high di/dt or ripple current can induce noise in nearby analog sense lines) — route BMS cell-sense and shunt-sense wiring in a separate harness/trace region from power busbars.

## Worked example: shunt sizing and battery backup runtime

**Shunt sizing for a 20 A max discharge Li-ion pack:**

1. Choose a shunt targeting ≤ 50 mV drop at max current for a typical current-sense amplifier's input range: R = V/I = 0.050/20 = 2.5 mΩ; round to a standard value, e.g., 2 mΩ.
2. Power dissipation at max current: P = I²×R = 20² × 0.002 = 0.8 W. Choose a shunt rated for at least 2x this (1.5–2 W rated part) for thermal margin and long-term drift stability.
3. Voltage measured at max current with 2 mΩ: V = 20 × 0.002 = 40 mV — verify this is comfortably within the current-sense amplifier's usable input range and above its offset-voltage error floor (e.g., if the amplifier has ±100 µV offset, that's a 0.25% error at full scale — acceptable; at 10% of full scale (2 A, 4 mV), the same 100 µV offset is now a 2.5% error — check whether low-current accuracy matters for your application, e.g., fuel gauging at low discharge rates).
4. Route as 4-wire Kelvin: two force traces carrying the full 20 A (sized per IPC-2152, see power_high_current_and_thermal.md), two sense traces as a tight differential pair to the amplifier, tapped from inside the shunt's current pads.

**UPS backup runtime for a 24 V industrial control load drawing 2 A, needing 15 minutes of backup:**

1. Required capacity: 2 A × 0.25 h = 0.5 Ah, i.e., 500 mAh at 24 V (12 Wh).
2. Apply depth-of-discharge and aging margin: for a sealed lead-acid battery limited to 50% practical DoD for cycle life, and budgeting 25% capacity loss over service life before replacement: required nameplate capacity ≈ 500 mAh / 0.5 / 0.75 ≈ 1.33 Ah — round up to a common size, e.g., a 1.3 Ah or 2.0 Ah 24 V (or 2×12V in series) SLA pack, or size a Li-ion/LiFePO4 pack similarly if DoD/aging margins are adjusted for that chemistry's typical usable range (LiFePO4 tolerates deeper DoD, so less over-sizing margin may be needed).
3. Charger/float voltage set per the chemistry (SLA float ~13.5–13.8 V per 12 V block, temperature-compensated if the enclosure sees wide ambient swings) and power-path ORing/ideal-diode sized to carry the 2 A load current with acceptable voltage drop during the mains-to-battery handover.

## Common mistakes

- Charging Li-ion without temperature qualification, risking lithium plating at low temperature or thermal runaway at high temperature/overvoltage.
- Relying on pack-level (single) voltage monitoring instead of per-cell monitoring in a multi-cell series stack — a single weak cell can be driven into overcharge or overdischarge while the pack average looks fine.
- Using 2-wire (non-Kelvin) shunt sensing, corrupting current measurement with trace/connector resistance.
- Omitting inrush limiting on hot-swappable boards, causing bus droop or connector damage.
- Sizing the fuse larger than the PCB trace or wire ampacity, so the trace becomes the fuse (and burns) instead of the intended protection device.
- Forgetting balancing entirely on multi-cell packs, leading to premature capacity fade and eventual cell imbalance/safety margin erosion.
- Using a simple diode OR without accounting for its forward-drop power loss and headroom requirement at high current.
- Not providing a redundant/independent protection path for critical OVP/UVP functions, relying solely on firmware in the primary BMS IC (a firmware hang or bug then removes protection entirely).

## Schematic review checklist

- [ ] Charge profile (CC-CV voltage/current thresholds, termination condition) matches the specific chemistry and cell count.
- [ ] Temperature sensing present and gates charge enable for Li-ion/LiFePO4 packs.
- [ ] Per-cell voltage monitoring present for series multi-cell packs (not pack-voltage-only).
- [ ] OVP/UVP/OCP/OTP protection paths defined, with independent/redundant protection considered for safety-critical packs.
- [ ] Balancing method (passive/active) chosen and balancing current/threshold specified.
- [ ] Protection FETs sized for Rds(on) conduction loss and SOA under worst-case fault current/duration.
- [ ] Current-sense shunt is 4-wire Kelvin, sized with power margin and appropriate tempco for the accuracy needed.
- [ ] Power-path (ORing/ideal-diode) topology chosen appropriately for the efficiency/complexity tradeoff of the application.
- [ ] Hot-swap/inrush control present on any board that connects to a live shared bus.
- [ ] Fuse/eFuse rating sized between normal operating current (with margin) and trace/wire damage current, placed near the source.

## Layout review checklist

- [ ] Kelvin sense traces for current-shunt and cell-voltage monitoring routed away from high-current paths, as tightly coupled differential pairs.
- [ ] High-current busbar/trace paths sized per current-density guidance and verified against IPC-2152 (see power_high_current_and_thermal.md).
- [ ] Fuse/protection device placed as close to the source (battery terminal) as practical, in the ungrounded conductor.
- [ ] Balancing resistors (passive balancing) have adequate copper/airflow for their dissipation, away from temperature-sensitive components.
- [ ] Protection FETs have adequate copper area/thermal vias for conduction loss dissipation under fault conditions.
- [ ] Bolted busbar/connector joints specify torque and hardware (star/Belleville washers) in fabrication notes.
- [ ] BMS analog front-end traces (cell taps) kept short and away from switching/high-di/dt busbar regions to avoid noise coupling.
- [ ] Separate ground/return referencing for BMS analog sensing vs high-current power return, joined at a single defined point to avoid ground loops.
