---
title: Layout Review Checklist
domain: general
tags: [layout review, stackup, placement, return paths, thermal, emc, dfm, silkscreen, fiducials, drc]
applies_to: [any pcb layout prior to fabrication release, design review]
---

## How to use this checklist

Run this after layout is complete and DRC-clean but before release to fabrication. Like the schematic checklist, walk the board deliberately region-by-region and signal-class-by-signal-class rather than eyeballing the whole board at once — high-consequence errors (a missing return path under a high-speed signal, a thermal via array that looks present but isn't actually connected to copper) are easy to miss on a casual visual pass.

## Stackup

- [ ] Stackup matches what was specified to the fabricator (layer count, copper weight per layer, dielectric material/thickness) — verify against the fab's actual stackup table for this order, not just the design intent, since a controlled-impedance design depends on the fab's real dielectric constant and thickness.
- [ ] Every signal layer has an adjacent reference plane (power or ground) for return-path continuity — no signal layer sandwiched between two other signal layers without a nearby plane.
- [ ] Controlled-impedance traces (USB, Ethernet, high-speed differential pairs) have their target impedance specified to the fab and the trace width/spacing on this stackup verified (via the fab's field-solver tool or a datasheet reference) to actually hit that target — see high_speed_signal_integrity.md and stackup_and_layer_count.md.
- [ ] Layer count and stackup appropriate for the design's actual complexity/speed per stackup_and_layer_count.md — neither under-specified (causing return-path/EMC problems) nor needlessly over-specified (unnecessary cost).

## Placement

- [ ] Connectors placed at board edges consistent with the enclosure/mechanical design, with orientation matching the intended cable/harness routing.
- [ ] Decoupling capacitors placed as close as physically possible to their IC's power pins, with the shortest practical loop to both the pin and the return plane via.
- [ ] Components grouped by function (power stage, analog front end, digital logic, RF) with clear physical separation between noisy and sensitive groups.
- [ ] Tall components checked against the enclosure's mechanical clearance, and against any nearby connector's mating/insertion clearance.
- [ ] Polarized/keyed components oriented consistently across the board where multiple identical instances exist, reducing assembly error risk.

## Return paths

- [ ] Every high-speed or sensitive signal has an unbroken, adjacent return path (reference plane directly below/above it) for its entire length — no signal routed over a plane split, a connector gap, or a layer-transition via without a nearby ground-stitching via.
- [ ] Layer-transition vias for critical signals have a nearby ground via (stitching via) providing a continuous return path across the layer change, per high_speed_signal_integrity.md.
- [ ] Ground plane free of unnecessary slots/cuts that would force a return current to detour around them, particularly beneath switching power converters, high-speed signals, and RF sections.
- [ ] Mixed analog/digital ground schemes (if used) reviewed for actual current flow, not just a conceptual split — verify no digital return current is forced to cross into the analog ground region.

## High current and thermal

- [ ] Every high-current trace/plane sized per an IPC-2152-based calculation (or equivalent) for its actual worst-case current and acceptable temperature rise, not estimated by eye — see power_high_current_and_thermal.md.
- [ ] Thermal vias present under every significant heat-generating component, actually connected to copper on the destination layer (verify in the 3D viewer or layer-by-layer, not just assumed from the footprint's via array).
- [ ] Copper pour/plane area allocated for heat spreading beneath high-dissipation components, sized against a real thermal estimate for worst-case ambient and load.
- [ ] Kelvin (4-wire) sense connections used for any precision current-shunt measurement, with sense traces routed away from the shunt's main current path per motor_drives_and_motion.md.
- [ ] Paralleled high-current switches or shunts laid out symmetrically so current shares evenly between them.

## Hot loops (switching power)

- [ ] Every switching converter's hot loop (input capacitor–switch–inductor/output, or equivalent for the topology) minimized in physical area per power_buck_boost_converters.md.
- [ ] Bootstrap capacitors and gate-driver-adjacent components placed with minimal trace length to their associated switch-node/driver pins.
- [ ] Switching nodes (high dv/dt) kept away from sensitive analog, RF, or high-impedance signal traces, with a ground-plane buffer where proximity can't be avoided.

## EMC

- [ ] Board edge/connector regions have appropriate ground stitching and, where required, a chassis-ground moat or connection point per protection_emc_esd.md.
- [ ] Clock and other periodic high-frequency signals routed away from board edges and external cable connectors, minimizing radiated emission risk.
- [ ] Common-mode filtering/chokes present at cable exit points where the design's EMC standard requires it (industrial field I/O, motor phase outputs, network interfaces).
- [ ] Shield connections (cable shields, RF can shields) terminated with short, low-inductance connections — no long pigtail leads defeating high-frequency shielding effectiveness.
- [ ] Crystal oscillators and their load capacitors placed close to the IC with short, symmetric traces and a solid local ground, away from switching noise sources.

## Isolation boundaries

- [ ] Creepage/clearance distances verified against the design's actual working voltage and pollution degree at every isolation boundary, with routed slots added where flat spacing alone is insufficient, per industrial_plc_io.md.
- [ ] No plane or trace bridges the isolation keepout on any layer, including inner layers that can be easy to overlook in a top-layer-only visual check.
- [ ] Isolated DC-DC converters and digital isolators physically straddle the isolation gap with no signal routed across the gap except through the intended isolator component.

## DFM (Design for Manufacturing)

- [ ] Minimum trace width/spacing, via size, and annular ring all within the target fabricator's stated capability (standard or advanced/HDI tier as appropriate) — see fab_order_checklist.md and dfm_dfa_fabrication_and_assembly.md.
- [ ] Via-in-pad (if used) specified with the correct fill/plate-over treatment the fab supports, not assumed to be automatically compatible with standard processing.
- [ ] Component-to-component and component-to-board-edge spacing meets the assembly house's placement/reflow clearance requirements.
- [ ] No components placed in the board's designated mounting-hole keepout, panel rail (if panelized), or v-score/tab-route breakout region.
- [ ] Solder mask slivers, minimum mask-defined-opening size, and paste-stencil aperture design reviewed against the fab/assembly house's capability, particularly for fine-pitch parts.

## Silkscreen

- [ ] Every component has a legible, correctly-oriented reference designator that doesn't overlap a pad, via, or another component's silkscreen after placement (not just correct in the schematic/footprint default position).
- [ ] Polarity markings (diode cathode, electrolytic capacitor negative terminal, connector pin 1) present and unambiguous on the silkscreen for every polarized part.
- [ ] Connector function/signal labeling present where field wiring or user-facing connections require it (matches industrial_plc_io.md's field-terminal labeling guidance).
- [ ] Board name/revision and, where relevant, a unique serial/date-code field present on the silkscreen or a dedicated marking layer.

## Fiducials and mounting

- [ ] Global fiducials placed per the assembly house's requirement (typically at least two diagonal corners) for pick-and-place vision alignment.
- [ ] Local fiducials added near any fine-pitch (e.g., 0.5mm or finer pitch BGA/QFN) component per the assembly house's guidance.
- [ ] Mounting holes sized and positioned per the enclosure/mechanical design, with appropriate keepout (no components/copper) around each hole per the fastener/standoff's actual clearance need.
- [ ] Mounting hole plating (plated vs. non-plated) and any required ground connection at mounting holes specified deliberately, not left at a tool default.

## DRC (Design Rule Check)

- [ ] DRC run with rules matching the actual fabricator's capability (not the CAD tool's default rule set) and the board's electrical requirements (clearance for the working voltage, not just a generic minimum).
- [ ] Every DRC violation individually reviewed and either fixed or explicitly waived with a documented reason — no blanket-ignored violation list.
- [ ] Unrouted nets count is zero, and airwires visually confirmed absent across the whole board, not just trusted from the DRC summary count.
- [ ] Copper-to-board-edge clearance meets the fab's minimum, especially around any routed slots or cutouts.

## Final pass

- [ ] 3D render/viewer reviewed for mechanical interference (tall components, connector clearance, enclosure fit) before release.
- [ ] Gerber/drill preview reviewed layer-by-layer in a separate viewer from the CAD tool (catches export-step errors the CAD tool's own view wouldn't show) — see fab_order_checklist.md.
- [ ] Layout reviewed by someone other than the original author where possible, focusing specifically on return paths, thermal, and isolation — the areas most prone to being visually plausible but electrically wrong.
