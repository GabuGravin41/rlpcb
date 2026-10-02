---
title: Bring-Up and Test Checklist
domain: general
tags: [bring-up, first power-on, current limit, rail check, sequencing, programming, functional test, thermal camera, fault injection]
applies_to: [first-article boards, prototype bring-up, production test planning]
---

## How to use this checklist

Follow this roughly in order — each stage is designed to catch a fault before it can damage the board or mask a later, harder-to-diagnose problem. Do not skip stages to "save time"; a board damaged during an unlimited-current power-on because the current-limited-supply stage was skipped costs far more time than the stage itself would have taken.

## Stage 1: visual and continuity inspection (before any power)

- [ ] Visually inspect the board under magnification for solder bridges, tombstoned components, missing components, and obviously wrong component values/orientations against the assembly drawing.
- [ ] Verify no continuity (near-zero resistance) exists between adjacent power rails, and between any power rail and ground, using a multimeter in resistance/continuity mode before applying any power — a dead short here, caught now, prevents a much worse outcome at power-on.
- [ ] Check polarized components (electrolytic capacitors, diodes, connectors) visually against the silkscreen polarity marks.
- [ ] Confirm the correct board revision and any required rework/ECO (engineering change order) has actually been applied, not just documented as intended.

## Stage 2: first power-on with current-limited supply

- [ ] Power the board from a bench supply with current limiting set conservatively (start well below the rail's expected normal current, e.g., 2-3x the expected quiescent/idle draw, not the full rated capacity) — this is the single most important habit in safe bring-up.
- [ ] Apply power to one rail at a time where the design allows isolating rails (e.g., disconnect downstream sub-boards, or populate regulators sequentially) rather than powering the entire board at once on the very first application.
- [ ] Watch the current draw immediately at power-on — a current that jumps straight to the limit and stays there indicates a fault (short, wrong component) and power should be removed immediately for investigation, not left connected "to see what happens."
- [ ] Check for any component getting hot to the touch within the first seconds of power application — an immediate, unexpected temperature rise is a strong fault indicator even before instrumented measurement.

## Stage 3: rail verification

- [ ] Measure every regulated rail's DC voltage at its test point against the design target, within the regulator's specified tolerance.
- [ ] Measure rail ripple/noise with an oscilloscope (AC-coupled, appropriate bandwidth) against the design's noise budget for that rail, particularly for any analog or high-speed digital supply.
- [ ] Verify each rail's quiescent current draw matches the expected value from the power budget calculation — a significantly higher-than-expected current at idle indicates a fault even if the voltage looks correct.
- [ ] Check regulator thermal performance (touch-test or, better, thermal camera per Stage 7) at expected idle load before proceeding to higher-current functional testing.

## Stage 4: power sequencing verification

- [ ] For any design with sequencing requirements (multi-rail processors, ICs needing core-before-IO or IO-before-core power-up order), capture all relevant rails simultaneously on a multi-channel oscilloscope during power-on and verify the actual sequence and timing matches the requirement.
- [ ] Verify power-good/reset-release timing relative to rail stabilization — confirm the reset signal releases only after all required rails are within tolerance, with adequate margin, not immediately as rails begin rising.
- [ ] Test power-down sequencing (if specified) the same way, since some ICs have shutdown-order requirements as strict as their power-up requirements.
- [ ] Test power-cycling behavior (rapid off/on, brief brownout) for any nuisance reset or lock-up behavior not apparent from a single clean power-up.

## Stage 5: programming and firmware bring-up

- [ ] Verify the programming/debug interface (SWD, JTAG, UART bootloader) connects and identifies the target device correctly before attempting to load application firmware.
- [ ] Load a minimal "blink an LED" or equivalent smoke-test firmware first, confirming basic clock/boot/GPIO function before attempting the full application firmware.
- [ ] Verify boot-mode strap pins actually produced the intended boot behavior (check against the schematic review's boot-pin verification) — a wrong boot mode is a common first-bring-up issue distinguishable from a firmware bug.
- [ ] Confirm any external memory (flash, RAM) the processor depends on is correctly detected/initialized before proceeding to more complex firmware.

## Stage 6: functional test, subsystem by subsystem

- [ ] Test each communication interface (I2C, SPI, UART, USB, Ethernet, CAN) individually with a known-good peer device or loopback test before relying on it for integrated system testing.
- [ ] Test each sensor/analog input against a known reference stimulus (calibrated source, known physical condition) and verify readback accuracy within the expected tolerance.
- [ ] Test each actuator/output (motor driver, relay, digital output) individually at reduced power/duty first, confirming correct polarity/direction/response before full-power operation.
- [ ] Exercise each subsystem across its intended operating range (not just a single nominal test point) — a sensor or driver that works at one condition but fails at range extremes is a common integration-testing gap.
- [ ] Verify any safety-relevant function (e-stop, overcurrent shutdown, thermal shutdown, watchdog) triggers correctly under deliberately induced fault conditions, not just assumed correct from the schematic review.

## Stage 7: thermal imaging

- [ ] Thermal-image the board under worst-case sustained load (not just idle) and compare hot-spot locations and temperatures against the design's thermal predictions.
- [ ] Identify any component running meaningfully hotter than its datasheet-predicted temperature at this load, which may indicate an undersized thermal path, an unexpectedly high actual power dissipation, or a layout thermal-via/copper issue.
- [ ] Re-check thermal performance after any layout rework, since even a well-intentioned fix can change the thermal path in an unreviewed way.
- [ ] For boards with forced-air or liquid cooling in the final product, run at least one thermal-imaging pass with the actual cooling solution installed, not only on an open bench with ambient convection, since bench conditions can be meaningfully more favorable than the enclosed product.

## Stage 8: fault injection

- [ ] Deliberately short an output that has overcurrent protection and verify the protection trips at the expected threshold and within the expected time, then recovers (or latches, per design intent) correctly.
- [ ] Disconnect a sensor/input mid-operation and verify the system reports a clear fault/wire-break condition rather than a plausible-but-wrong reading (see industrial_plc_io.md wire-break detection principle).
- [ ] Remove power abruptly during an active operation (e.g., mid-write to nonvolatile memory, mid-motor-motion) and verify the system recovers cleanly on the next power-up rather than entering a corrupted or unsafe state.
- [ ] For any redundant/safety architecture, individually fail each redundant channel/lane and verify the system correctly detects the fault and, where specified, continues safe operation on the remaining channel(s).
- [ ] Inject a communication-bus fault (disconnect, wrong termination, noise injection where practical) and verify the system's error-handling behavior rather than only testing the clean-bus case.

## Stage 9: EMC and environmental pre-checks (where applicable)

- [ ] Basic conducted/radiated emissions pre-scan (even with a near-field probe and spectrum analyzer, short of full compliance testing) to catch gross EMC problems before formal compliance testing.
- [ ] Apply representative ESD/surge/EFT transients (per the applicable IEC 61000-4-x or equivalent standard's test level for the product class) and verify no latch-up or permanent damage.
- [ ] Temperature-cycle or at minimum verify functional operation across the specified operating temperature range using an environmental chamber if the product's deployment environment has meaningful temperature variation.

## Stage 10: sign-off

- [ ] Every checklist item above either passed or has a documented, accepted deviation with a clear owner and follow-up plan — no silent skips.
- [ ] Bring-up results (rail voltages, quiescent currents, thermal images, fault-injection outcomes) recorded in a durable location for comparison against future units and future design revisions.
- [ ] Any issue found during bring-up fed back into the schematic/layout review checklists so the root cause (not just the symptom) is addressed before the next revision or production run.
