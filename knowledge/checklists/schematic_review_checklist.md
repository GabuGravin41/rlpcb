---
title: Schematic Review Checklist
domain: general
tags: [schematic review, erc, decoupling, reset, boot pins, pull-ups, esd, connectors, footprints, net naming]
applies_to: [any schematic prior to layout, design review, pre-release review]
---

## How to use this checklist

Run this checklist after the schematic is functionally complete but before starting layout — catching an error here costs minutes; catching the same error after layout or fabrication costs hours to weeks. Go net-by-net and sheet-by-sheet rather than skimming; most real schematic errors are found by deliberately tracing individual signals, not by reading circuits top-to-bottom as prose.

## Power architecture

- [ ] Every IC's supply voltage and current requirement identified and matched to an actual regulated rail on the schematic — no IC connected to a rail "close enough" to its rated voltage without checking the datasheet's absolute min/max.
- [ ] Power tree diagram (even a hand-drawn one) exists showing every rail's source, its downstream loads, and worst-case total current — this should exist before layout, not be reverse-engineered from the schematic afterward.
- [ ] Each regulator's input voltage range, output current capability, and thermal dissipation checked against its actual worst-case load, not just typical/nominal load.
- [ ] Power sequencing requirements (if any IC needs rails to come up/down in a specific order — common on processors with separate core/IO voltages) implemented via sequencing logic or verified inherent in the regulator topology, not assumed.
- [ ] Reverse-polarity and overvoltage protection present on every externally-facing power input.
- [ ] Every rail has a clear, unambiguous net name used consistently across all sheets (see net naming below).

## Decoupling and bulk capacitance

- [ ] Every IC has local decoupling capacitance per its datasheet's recommendation (typically 100nF ceramic per power pin at minimum, plus larger bulk capacitance per functional block) — see power_decoupling_and_pdn.md for sizing methodology.
- [ ] High-speed/high-di/dt ICs (processors, FPGAs, DDR memory) have the specific decoupling network (multiple capacitor values spanning different frequency ranges) their datasheet or reference design specifies, not a generic single-value assumption.
- [ ] Bulk capacitance present at the point each regulated rail enters a populated board region, sized for that region's transient current demand.
- [ ] Decoupling capacitor voltage rating has adequate margin above the rail voltage (accounting for ceramic capacitors' DC-bias capacitance derating, not just the printed voltage rating).

## Reset circuits

- [ ] Every processor/MCU/FPGA reset input has a defined, deliberate reset circuit (RC delay, dedicated supervisor/reset IC, or the SoC's internal power-on-reset relied upon only where the datasheet explicitly permits it) — not a floating or assumed-pulled reset pin.
- [ ] Reset supervisor (if used) threshold voltage and delay time checked against the actual rail's power-up ramp characteristics — a threshold set too close to nominal voltage risks nuisance resets from normal ripple/noise.
- [ ] Manual reset button (if present) debounced (RC filter) and ESD-protected if user-accessible.
- [ ] Watchdog reset path (if used) verified to actually reach the intended reset pin/circuit, not left as a documented-but-unconnected intention.

## Boot/strap pins

- [ ] Every boot-mode/strap pin's required state at power-up identified from the datasheet and explicitly set (pull-up or pull-down resistor to the correct level) — never left floating on the assumption of an internal default that may not exist or may differ from the assumed value.
- [ ] Strap pin pull resistor values checked against the datasheet's specified range (too weak a pull can be overridden by another connected device; too strong wastes power or violates a max-current spec on some parts).
- [ ] Boot-mode pins that are also used as normal GPIO after boot (common on many MCUs) reviewed for conflict with the external circuit connected to that pin during the boot-sampling window.
- [ ] Dedicated boot-select header/jumper (if the design supports field reconfiguration of boot mode) clearly labeled with each position's function.

## Pull-ups and pull-downs

- [ ] Every open-drain/open-collector signal (I2C SDA/SCL, some interrupt lines, some enable lines) has an appropriately sized pull-up resistor — I2C pull-up value calculated against actual bus capacitance and target speed (standard/fast/fast-plus mode), not copied from an unrelated design.
- [ ] Every input pin that must not float in a defined state during any operating condition (including before firmware initializes GPIO direction/pull configuration) has an explicit external pull-up or pull-down.
- [ ] Unused input pins on ICs (spare GPIO, unused function-select pins) tied to a defined level per the datasheet's guidance for unused pins, not left floating.

## ESD and transient protection

- [ ] Every user-accessible or field-wiring-accessible connector pin has ESD/TVS protection appropriate to its exposure (see protection_emc_esd.md and, for field I/O, industrial_plc_io.md).
- [ ] TVS/ESD protection component specified with standoff voltage above the line's normal operating range and clamping voltage below the protected IC's absolute maximum rating.
- [ ] USB, Ethernet, and other standard interface connectors have the ESD protection the relevant interface specification/reference design calls for, not just a generic assumption of "connector ICs have some ESD rating already."

## Connectors and footprint assignment

- [ ] Every connector's pinout cross-checked against its actual mating connector/cable, not just the connector manufacturer's generic pin-numbering convention (pin 1 orientation errors are a common, easily-missed source of reversed/swapped signals).
- [ ] Every schematic symbol has a footprint assigned before netlist/BOM generation, and that footprint verified against the actual part's mechanical drawing (pad pitch, pad size, polarity marking) — not just trusted from a library default.
- [ ] Polarized components (electrolytic/tantalum capacitors, diodes, connectors) have their polarity clearly and consistently indicated in both schematic symbol and footprint.
- [ ] Mounting/mechanical connectors (board-to-board, edge connectors) checked for correct gender and keying against the mating half.

## DNP (Do Not Populate) and variant management

- [ ] Every DNP (do-not-populate) component clearly marked as such in the schematic (not just omitted from a separately-maintained BOM note that could drift out of sync).
- [ ] DNP components' effect on circuit function documented — if a DNP resistor leaves a node floating or a feedback path open, confirm that's the intended state for that variant, not an oversight.
- [ ] If the design supports multiple populated variants (e.g., different sense-resistor values for different current ranges), each variant's complete BOM state is captured, not just the "default" variant.

## Test points

- [ ] Test points provided for every rail requiring bring-up verification (see bring_up_and_test_checklist.md) — accessible without needing to probe a fine-pitch IC pin directly.
- [ ] Test points provided for critical signals needed for production test/programming (SWD/JTAG, UART console, key communication bus signals).
- [ ] Test point net names match the schematic's signal names for unambiguous reference during bring-up.

## Net naming and hierarchical sheets

- [ ] Net names are consistent and unambiguous across the entire design — the same signal never has two different names on different sheets, and two different signals never accidentally share a name (a common cause of unintended shorts via global labels).
- [ ] Power rail net names follow a clear, consistent convention (e.g., +3V3, +5V, GND) used identically everywhere that rail appears.
- [ ] Hierarchical sheet pins and the corresponding hierarchical labels on the parent sheet match in name, direction (input/output/bidirectional), and count — a mismatched hierarchical pin is a common source of an apparently-connected net that is actually open.
- [ ] Global labels used deliberately (for genuinely global signals like power rails and system-wide resets/clocks) rather than as a substitute for proper hierarchical sheet connections, which can obscure the actual signal flow between sheets.

## ERC (Electrical Rules Check)

- [ ] ERC run and every warning/error individually reviewed and either fixed or explicitly justified (not blanket-suppressed) — see kicad_wiring_howto.md for running ERC in KiCad.
- [ ] No unintended unconnected pins reported by ERC — every "no-connect" is a deliberate no-connect flag (KiCad's X/no-connect symbol), not simply an unwired pin ERC happens to not flag.
- [ ] No pin-type conflicts (e.g., two outputs driving the same net) reported by ERC without a documented reason (such as an intentional, protected bus-contention-tolerant design).
- [ ] Power-input pins verified to actually trace back to a power symbol/net on every sheet, not accidentally left disconnected on a hierarchical sheet instance.

## Final pass

- [ ] Schematic reviewed by someone other than the original author where possible — a second set of eyes catches assumption-driven errors the original designer is blind to.
- [ ] Every design decision that deviates from a datasheet's reference design or an established pattern in this knowledge base is documented with a reason, so a future reviewer (including the original author, months later) understands why.
- [ ] Revision history/date updated on the schematic title block before release to layout.
