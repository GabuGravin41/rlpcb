---
title: UPS and Battery Backup System Reference Architecture
domain: power
tags: [ups, online, line-interactive, battery charger, inverter, bms, transfer switch, isolation, safety]
applies_to: [ups boards, battery backup boards, inverter boards, battery management boards]
---

## Topology overview: choosing a UPS class

- **Standby (offline)**: mains normally passes through to the load via a bypass relay; the inverter/battery only engages when mains fails, with a brief (typically 4–12 ms) transfer gap. Simplest and cheapest, adequate for equipment tolerant of a short power interruption. Not covered in depth here — the line-interactive and online architectures below are the common industrial/serious-application choices.
- **Line-interactive**: mains passes through an autotransformer (buck/boost tap-switching) that corrects moderate over/under-voltage without switching to battery, improving voltage regulation over standby without the cost/complexity of a full double-conversion inverter; still has a brief transfer gap on full mains loss, and the inverter is only active during outages.
- **Online (double-conversion)**: mains is rectified to a DC bus continuously, and the inverter continuously regenerates the AC output from that DC bus at all times — the battery simply floats on the same DC bus, ready to sustain it instantly on mains loss with **zero transfer time** since the inverter never stops running. This is the standard architecture for critical loads (servers, medical, industrial process control) where even a few-millisecond gap is unacceptable, at the cost of continuous double-conversion efficiency loss (typically 90–96% efficient depending on load and design, versus line-interactive's near-100% efficiency when on mains).

This guide focuses primarily on the online double-conversion architecture since it's the reference design most applicable to industrial-grade backup power, noting line-interactive differences where relevant.

## Power tree (online double-conversion)

- **PFC rectifier stage**: mains AC (single-phase 120/230 VAC or 3-phase 208/400 VAC depending on UPS power class) into a power-factor-corrected boost rectifier producing a regulated DC bus, commonly 380–400 VDC for single-phase or higher for 3-phase designs — PFC is required both for regulatory compliance (IEC 61000-3-2 harmonic limits) and to present a near-unity power factor load to the mains.
- **DC bus**: the regulated PFC output bus, buffered by substantial electrolytic bulk capacitance, is the common node the battery charger draws from and the inverter draws from — sized for the ride-through energy needed during the PFC's own transient response and for inverter pulse current demand.
- **Battery charger stage**: a buck (or bidirectional buck-boost) converter from the DC bus down to the battery string voltage (commonly 12 V/24 V/48 V per string for small-to-mid UPS, scaling to hundreds of volts for large 3-phase online UPS with long strings of VRLA or Li-ion cells) — implements the appropriate charge profile (see battery charging below).
- **Inverter stage**: a full-bridge (single-phase) or 3-phase bridge inverter from the DC bus (whether sourced from PFC-rectified mains or from the battery during an outage — the inverter doesn't care which, since both feed the same DC bus) producing regulated AC output, typically via an LC output filter to produce a clean sine wave and an isolation transformer in many designs (see isolation below).
- **Bypass path**: a static bypass switch (SCR or relay-based) that can connect mains directly to the output, used during inverter fault conditions, overload beyond inverter capacity, or maintenance bypass — bypass switching must be make-before-break or otherwise glitch-managed to avoid an output interruption during the switchover.

## Key part families

- **PFC controllers**: boost-PFC controller ICs (e.g., TI UCC28070-class, onsemi/Infineon PFC controllers) for continuous-conduction-mode boost PFC front ends.
- **Inverter/charger control**: digital power controllers or dedicated DSP/MCU (e.g., TI C2000-class) running the double-conversion inverter and charger control loops.
- **BMS ICs**: multi-cell battery monitor/balancer ICs (e.g., TI BQ769x-class, Analog Devices LTC68xx-class) for Li-ion string monitoring and protection.
- **Battery contactors/disconnects**: high-current relays or solid-state contactors rated for the string's fault current, used for the BMS-independent disconnect path.
- **Isolation**: line-frequency isolation transformers (transformer-based designs) or reinforced-isolation-rated components (transformerless designs) per IEC 62368-1.
- **Static bypass switch**: SCR modules or high-current relays for the bypass path, sized for worst-case fault current during transfer.

## Battery charging and BMS

- **Charge profile**: VRLA (valve-regulated lead-acid) batteries use a float-charge profile (constant voltage, temperature-compensated, typically ~2.25–2.30 V/cell at 25°C float) with occasional boost/equalize charging; Li-ion (increasingly common in modern UPS for weight/lifespan advantages) requires a CC/CV (constant-current, constant-voltage) profile with cell-level balancing — see power_battery_bms_ups.md for detailed charging/BMS electrical design.
- **Temperature compensation**: VRLA float voltage must be temperature-compensated (typically around −3 to −5 mV/°C/cell) since lead-acid charge acceptance and gassing threshold both shift with temperature — omitting this shortens battery life significantly in installations with meaningful ambient temperature swing (e.g., unconditioned equipment rooms).
- **BMS for Li-ion strings**: cell-level voltage monitoring and balancing (passive resistive or active), string current sensing, and independent overvoltage/undervoltage/overtemperature protection separate from the main charger control loop — the BMS's protection function should be capable of disconnecting the battery (via a contactor or high-current MOSFET) independent of the charger/inverter firmware, mirroring the general principle (seen throughout this knowledge base) that a safety-critical cutoff function shouldn't depend solely on the same control path it's meant to protect against.
- **Battery disconnect/fusing**: a manual/service disconnect plus a fuse or circuit breaker sized for the battery string's maximum fault current (which can be very high for large VRLA/Li-ion strings — battery internal impedance is low) is standard; this is as much a fire-safety requirement as an electrical-design one.

## Inverter and output stage

- Full-bridge or 3-phase bridge topology switched at a PWM frequency (commonly several kHz to tens of kHz) with sinusoidal PWM or space-vector modulation, followed by an LC low-pass filter to reconstruct a clean sine wave from the PWM output.
- Output isolation: many online UPS designs include a line-frequency (50/60 Hz) isolation transformer at the output, or in transformerless designs rely on the PFC/inverter topology and appropriate creepage/clearance/isolation-rated components to achieve the required safety isolation — transformerless designs are lighter/more efficient but require more careful attention to leakage current and ground-fault behavior; transformer-based designs are heavier but provide straightforward galvanic isolation and often simpler regulatory compliance.
- Output overload/short-circuit protection: the inverter stage needs fast current limiting (cycle-by-cycle or per-switching-period) independent of the bypass switch's own protection, since a shorted output must not destroy the inverter switches before bypass or breaker protection can react.
- Load transfer to bypass: when the inverter can't sustain the load (severe overload, internal fault) the static bypass switch engages — this transition should be tested to avoid an output glitch large enough to disrupt the connected load's own power supplies.

## Isolation and safety

- Galvanic isolation between mains input, battery, and output is a core safety architecture decision — an online UPS with a transformer-isolated inverter output provides clean separation; a transformerless design still needs isolation appropriate to the standard the product is certified against (commonly IEC 62040-1 for UPS safety, referencing IEC 62368-1's general electronic equipment safety framework, and IEC 60950-1/62368-1 creepage/clearance tables per industrial_plc_io.md).
- Ground-fault and leakage current: UPS output ground referencing must be handled carefully, especially in transformerless designs — an incorrectly referenced neutral/ground on the UPS output can create leakage current or defeat downstream ground-fault protection on the load side; this is a systems-level design decision requiring the finished-product safety standard's specific guidance, not a generic PCB rule.
- Battery safety: VRLA batteries vent hydrogen gas during charging (requiring ventilation in the enclosure design, an electrical/mechanical systems concern) and Li-ion batteries require thermal runaway mitigation (cell spacing, thermal fusing, BMS protection as above) — both are enclosure/systems-level safety requirements that the board-level BMS/charger design must support but cannot fully solve alone.

## Layer count and stackup

- Power stage board (PFC + charger + inverter): 4–6 layers typical, with wide/thick copper (2 oz or heavier) for the high-current DC bus, battery, and inverter output paths — see power_high_current_and_thermal.md for high-current trace/copper sizing.
- Control/monitoring board (if separate from power stage): 4 layers typical, handling PFC/inverter PWM control, battery monitoring ADC front ends, and communication (see below) — kept physically separated from the power stage's switching noise where practical, connected via a defined, filtered interface.

## Communication and monitoring

- **PMBus/I2C or proprietary serial link to a monitoring MCU**: reports DC bus voltage, battery voltage/current/temperature, load percentage, and fault status — see load_balancing_and_power_distribution.md for PMBus principles applicable here.
- **Network management card interface** (common in mid/large UPS): a plug-in card providing SNMP/network monitoring, typically connected via a standard internal connector (RS-232 or USB-based in many product families) — designing this interface to an open, documented internal protocol (even if proprietary) makes field diagnostics and third-party monitoring integration far easier than a fully closed design.
- Audible/visual alarm outputs (buzzer, LED, relay contact for dry-contact remote alarm) for on-battery, low-battery, overload, and fault conditions — dry-contact relay outputs let the UPS report status into a building management or industrial control system without a network dependency, valuable as a fallback path.

## Test and bring-up plan

1. Bring up the PFC/rectifier stage first on a current-limited AC source, verifying DC bus regulation and power factor before connecting charger or inverter stages.
2. Bring up the charger stage with a bench electronic load simulating the battery (or a small test battery with current limiting), verifying charge profile (voltage/current) against the intended chemistry's specification before connecting the real battery string.
3. Bring up the inverter stage with the DC bus powered from a bench supply (not yet from PFC or battery) and a resistive dummy load, verifying output waveform, regulation, and protection response to a simulated overload/short before connecting real loads.
4. Full integration test: simulate a mains-loss event with a real (or simulated) load connected, verifying seamless (online) or within-spec (line-interactive) transfer, and battery run-time under a known load matches the design calculation.
5. Bypass transfer test: force an inverter fault/overload condition and verify bypass engages cleanly without an output glitch that would disrupt a sensitive downstream load.
6. Battery protection test: simulate an overtemperature or cell-imbalance fault (where safely possible with a test fixture) and verify the BMS disconnects the battery independent of charger/inverter firmware state.
7. EMC/harmonics pre-compliance: verify PFC input current harmonics against IEC 61000-3-2 and conducted/radiated emissions against the applicable UPS EMC standard before final certification testing.

## Common failure modes

- Battery charger without temperature compensation, shortening VRLA battery life in installations with significant ambient temperature variation.
- BMS protection function that depends on the same MCU/firmware as normal charge control, so a firmware hang leaves the battery unprotected during exactly the fault condition the BMS exists to catch.
- Transformerless output design with an incorrectly referenced neutral, creating leakage current that trips downstream GFCI/RCD protection on the load side.
- Bypass transfer causing an output glitch large enough to reset or disrupt sensitive downstream equipment, discovered only during full-load integration testing.
- Inverter output current limit too slow to protect switches during a hard output short, relying instead on an upstream breaker that reacts too slowly for the semiconductor's actual failure timescale.
- Undersized battery disconnect fuse/breaker for the string's actual fault current, or oversized to the point it doesn't protect against a realistic internal fault.

## Schematic review checklist

- [ ] PFC stage meets the target harmonic standard (IEC 61000-3-2) at the rated power range.
- [ ] Charger implements the correct profile (temperature-compensated float for VRLA, CC/CV with balancing for Li-ion) for the actual battery chemistry used.
- [ ] BMS protection (over/undervoltage, overtemperature, overcurrent) can disconnect the battery independent of charger/inverter firmware.
- [ ] Inverter has fast, cycle-level overcurrent/short-circuit protection independent of upstream breaker/fuse timing.
- [ ] Isolation (transformer or equivalent) and creepage/clearance meet the applicable UPS safety standard for input/output/battery domains.
- [ ] Battery disconnect fuse/breaker sized for the string's actual fault current.
- [ ] Bypass switch logic verified to avoid an output glitch during transfer.

## Layout review checklist

- [ ] High-current DC bus, battery, and inverter output paths use adequately wide/thick copper per power_high_current_and_thermal.md.
- [ ] PFC/inverter switching hot loops minimized per power_buck_boost_converters.md principles.
- [ ] Control/monitoring circuitry physically separated from power-stage switching noise, with a filtered interface between domains.
- [ ] Isolation boundary (mains/battery/output) maintained as a defined keepout with correct creepage/clearance on every layer.
- [ ] Battery connection uses adequately sized connectors/busbar for the string's maximum discharge current, with Kelvin sensing for BMS voltage measurement where required.
- [ ] Thermal design (copper area, vias) accounts for continuous double-conversion operation, not just peak/transient load.
