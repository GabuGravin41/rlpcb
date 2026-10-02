---
title: Clock Distribution and RF Basics
domain: rf
tags: [crystal, oscillator, clock-distribution, antenna, 2.4GHz, matching-network, coplanar-waveguide, via-fence]
applies_to: [digital, RF, wireless]
---

## Crystal vs oscillator

- **Crystal (passive)**: needs an on-chip or external oscillator circuit (Pierce oscillator, typically built into the MCU/IC) plus two load capacitors — cheaper, but the oscillator circuit's characteristics (and the layout) affect startup reliability and frequency accuracy. See `microcontroller_and_fpga_boards.md` for the CL calculation.
- **Oscillator (active, XO/TCXO/OCXO)**: a self-contained module with power, ground, output, and often an enable pin — no load caps needed, more predictable and easier to lay out, but higher cost and power. TCXO (temperature-compensated) is used where frequency stability over temperature matters (e.g., cellular/GNSS reference clocks); OCXO (oven-controlled) where very high stability is needed (rare outside precision timing/lab equipment).
- Use an active oscillator instead of a crystal when: the clock must drive multiple loads without a distribution buffer, the frequency tolerance requirement is tight enough that layout-induced parasitic variation is a risk, or board space right at the IC's oscillator pins is too constrained for a clean crystal layout.

## Clock distribution

- For a single clock feeding multiple ICs, use a dedicated **clock buffer/fanout IC** rather than routing one oscillator output to many loads directly — a clock buffer provides multiple low-skew, matched-impedance outputs and isolates the source oscillator from each load's capacitance, preserving edge rates.
- Match trace lengths between buffer outputs feeding devices that need synchronized clock edges (e.g., multiple PCIe REFCLK outputs, DDR clock fan-out) — see length-matching guidance in `high_speed_signal_integrity.md`.
- Terminate clock traces per the buffer/receiver's requirement — many LVDS/LVPECL clock outputs need a specific termination network (e.g., 100 Ω differential termination for LVDS, or a Thevenin/AC-coupled termination for LVPECL) defined in the buffer's datasheet; do not leave a fast clock trace unterminated and assume it will be fine.
- Keep clock traces away from other signals to minimize crosstalk — clocks are often the worst EMI offender on a board precisely because they're periodic, high-amplitude, and present continuously.

## 2.4 GHz antenna design (Wi-Fi/BLE/Zigbee class)

- **Chip antenna**: a small pre-tuned ceramic or module antenna soldered onto the PCB — simplest to lay out but needs the manufacturer's exact reference layout (ground clearance/keepout area, feed trace length, matching component footprint) followed precisely; deviating from the reference layout detunes it and degrades performance, often invisibly (it will still "work" at short range while being far below spec).
- **PCB (trace) antenna**: an antenna pattern etched directly in copper (e.g., inverted-F, meander, or monopole patterns) — zero component cost but requires either a validated reference design from the RF module/chip vendor or RF simulation/tuning with a VNA; not recommended to design from scratch without RF measurement equipment for anything beyond a hobby-range link.
- **Keepout area**: nearly all antenna types require a ground-and-component-free clearance zone around the antenna element (commonly extending several to tens of mm beyond the antenna edge, plus a "no ground plane" area directly under/near it if the antenna relies on radiating into that space) — check the specific antenna/module datasheet's keepout diagram; violating it is one of the most common causes of poor real-world RF range despite a design that "looks fine."
- Route the RF feed trace as a 50 Ω controlled-impedance microstrip (or coplanar waveguide, below) from the RF IC/module output directly to the antenna feed point, as short as possible, with no vias if avoidable (each via adds inductance/reflection at RF frequencies).

## Matching networks (pi network)

- A **pi-matching network** (shunt-series-shunt, typically using two capacitors and one inductor, or various LC combinations depending on the required impedance transformation) is placed between an RF IC's output and the antenna (or between stages) to transform impedance for maximum power transfer and to compensate for the specific antenna's actual impedance (which often isn't exactly 50 Ω, especially for PCB trace antennas).
- Component placement order and footprint matter — many RF IC vendors specify exact placement (e.g., "component closest to IC pad must be the series element" or similar) in their reference layout; deviating changes the effective network topology.
- Start from the module/chip vendor's reference matching network values as a first pass; final tuning (adjusting component values against measured return loss with a VNA) is standard practice for a production RF design, though not usually required at prototype/hobby scale if using a certified pre-matched module.
- Leave the matching network's footprints on the PCB even if using default/nominal values, so tuning is possible later without a re-spin — a common practice is to populate a 0 Ω / DNP (do-not-populate) placeholder for common alternate topologies.

## RF module integration

- Prefer a certified, pre-matched **RF module** (integrated chip + crystal + matching network + sometimes antenna, already regulatory-certified, e.g., FCC/CE-certified Wi-Fi/BLE modules) over a raw RF IC design when regulatory certification, faster time-to-market, or lack of RF test equipment are constraints — you inherit the module's certification as long as you follow its reference layout and don't modify the RF section, per the module's integration guide (each certifying module vendor publishes exactly what you're allowed to change while retaining modular certification — read it).
- Even with a certified module, follow the module's own PCB layout guide exactly for the antenna feed, ground clearance, and any required keepout — modular certification is typically conditional on matching the reference layout for RF-relevant sections.

## Coplanar waveguide (CPWG)

- **Coplanar waveguide with ground (CPWG)**: a signal trace with ground pour on either side (on the same layer) in addition to a reference plane below, giving an additional impedance-control parameter (gap to the side ground) beyond microstrip's single parameter (trace width vs plane distance) — useful when trace width alone can't hit the target impedance in the available dielectric thickness (common at RF frequencies with thin high-frequency laminates), or when a designer wants a tighter, mode-controlled RF transmission line.
- CPWG requires the side ground pours to be stitched to the bottom reference plane frequently (via stitching, spaced well under a wavelength at the operating frequency, commonly a fraction of an inch at sub-6 GHz) to suppress unwanted modes and keep the structure behaving as intended.
- Many RF IC/module vendors specify CPWG explicitly for their RF output trace (rather than plain microstrip) — follow the exact gap/width dimensions given, since CPWG impedance is sensitive to both parameters simultaneously.

## Via fencing

- A **via fence** (a row of ground vias stitched at regular intervals, commonly spaced at a small fraction of a wavelength at the frequency of concern) along the edges of an RF trace or around a sensitive RF section suppresses parallel-plate and edge radiation modes and improves isolation between adjacent RF/digital sections.
- Also used around board edges and connector cutouts on RF-sensitive boards to reduce EMI leakage and improve shielding effectiveness when combined with a metal shield can soldered to the fence's ground vias.
- Spacing rule of thumb: keep via-to-via spacing well under one-tenth of a wavelength at the highest frequency of concern for effective suppression (at 2.4 GHz, wavelength ≈ 125 mm in air, so well under ~12 mm spacing; tighter for good margin, commonly 2–5 mm spacing is used in practice).

## Oscillator startup and negative resistance

- A Pierce oscillator (the standard crystal-driving topology built into most MCU oscillator pins) needs the active device (the MCU's internal inverter) to present enough **negative resistance** at the crystal's frequency to overcome the crystal's equivalent series resistance (ESR, given on the crystal datasheet, commonly tens of ohms up to a few hundred ohms for low-frequency crystals) and start oscillating reliably across temperature and supply voltage corners.
- Excess load capacitance (oversized C1/C2, or excessive stray capacitance from long traces) reduces the effective negative resistance margin and is a common, hard-to-diagnose cause of intermittent oscillator startup failure — especially at cold temperature, where crystal ESR tends to rise.
- If a design shows intermittent no-boot behavior that resolves with a power cycle, oscillator startup margin (drive level, load cap sizing, layout parasitic capacitance) is one of the first things to check, alongside brown-out/reset timing.
- Crystal **drive level** (maximum power the crystal can safely dissipate, given in the datasheet, commonly under 100–500 µW for small SMD crystals) should not be exceeded — most MCU oscillator circuits include an internal series resistor or automatic gain control to manage this, but for external discrete oscillator circuits, add a series resistor (typically tens to a few hundred ohms) between the amplifier output and the crystal if the datasheet's drive-level budget requires it.

## Real-time clock (RTC) crystals

- 32.768 kHz "watch" crystals used for RTC functions are extremely low-power, low-drive-level parts (drive level often under 1 µW) and are proportionally more sensitive to layout parasitics and coupled noise than a higher-frequency main clock crystal.
- Keep 32.768 kHz crystal traces short, guarded, and away from any switching digital signal or switching regulator — coupled noise at this low frequency and low signal level can cause missed RTC ticks or complete startup failure.
- RTC crystal load capacitance is typically smaller (commonly 6–12.5 pF CL) than a main system crystal — use the same CL formula from `microcontroller_and_fpga_boards.md`, but do not reuse a main-clock crystal's load cap values for the RTC crystal.

## Frequency planning and spread-spectrum clocking

- When a design has multiple clock domains (e.g., a main system clock, a USB clock, an Ethernet PHY clock, an RF reference), avoid integer or near-integer harmonic relationships between them where practical — coincident harmonics can beat together and create difficult-to-filter EMI spurs that show up specifically at certain frequency offsets during compliance testing.
- **Spread-spectrum clocking (SSC)**: some clock sources/PLLs offer a mode that deliberately dithers the clock frequency by a small percentage (commonly under ±0.5%) at an audio-range modulation rate, spreading a clock's radiated energy across a wider frequency band and reducing peak emissions for EMI compliance — commonly used on PCIe and other high-speed serial clocks where the receiver's clock-recovery circuit can tolerate the induced jitter (check the specific interface spec/PHY for SSC compatibility before enabling it, since not every receiver tolerates it, and it must not be applied to REFCLK feeding a device expecting a clean reference for SRNS-style clocking without confirming compatibility).

## RF module thermal and power supply considerations

- RF transmit power draws a current spike during transmission bursts (Wi-Fi/BLE modules can draw several hundred mA momentarily during a TX burst even though average current is much lower) — size the module's supply decoupling (a mix of bulk capacitance, commonly 10–47 µF, plus local high-frequency decoupling) to handle this transient without the supply rail sagging enough to reset the module or corrupt an ADC/RF measurement elsewhere on the board.
- A regulator feeding an RF module should have adequate transient response and low output impedance at the frequencies the TX burst's current step contains — a slow, high-ESR linear regulator or an under-compensated switching regulator can show visible supply droop coincident with TX bursts, sometimes visible as brownout resets timed suspiciously with radio activity.

## Antenna diversity and placement on the board edge

- Place antennas (chip, PCB trace, or connector-fed external) at the board's edge, oriented away from other metal (large ground pours, shielding cans, batteries, connectors) that could detune or shadow the radiation pattern — an antenna placed in the board's interior surrounded by ground pour and metal enclosure walls will underperform its datasheet specification regardless of how well the matching network is tuned.
- For designs with an enclosure, verify the enclosure material (metal enclosures attenuate RF significantly; even some "plastic" enclosures use metallized coatings for EMI shielding that will also block the antenna) doesn't sit directly over/around the antenna's keepout area — check enclosure material with the mechanical/industrial design team early, since this is a common integration failure discovered only at final RF testing.

## Quick reference: typical clock/RF component values

| Item | Typical value | Notes |
|---|---|---|
| MCU crystal frequency | 8–25 MHz | Main system clock, exact value per MCU/PLL requirements |
| MCU crystal CL | 6–20 pF | Datasheet-specified, drives load cap sizing |
| RTC crystal frequency | 32.768 kHz | 2^15 Hz, divides cleanly for 1 Hz timekeeping |
| RTC crystal CL | 6–12.5 pF | Smaller than main clock crystals |
| Crystal ESR (main clock) | 20–100 Ω | Lower is better for easier startup |
| Crystal ESR (32.768 kHz) | 30–100 kΩ | Much higher; sensitive to layout noise |
| Load cap value (typical) | 10–22 pF | Computed per CL formula, standard values |
| 2.4 GHz wavelength (air) | ~125 mm | Used for via-fence/keepout spacing rules |
| Via fence spacing target | 2–5 mm | Well under 1/10 wavelength at 2.4 GHz |
| Pi-network component count | 2 cap + 1 inductor (typ.) | Topology varies by vendor reference design |
| SSC modulation depth | ≤ 0.5% | Typical down-spread setting for PCIe-class clocks |
| RF module TX burst current | 200–500 mA | Momentary; sizes bulk decoupling |
| Antenna keepout clearance | Several–tens of mm | Always per specific antenna/module datasheet |

## Worked example: 25 MHz crystal load cap selection

A 25 MHz crystal specifies CL = 8 pF. Estimated board/pin stray capacitance Cstray ≈ 3 pF (typical assumption absent a datasheet pin-capacitance figure). Solve for C1 = C2 = C:

```
CL = (C*C)/(C+C) + Cstray
8 = C/2 + 3
5 = C/2
C = 10 pF
```

Select two 10 pF (or nearest standard, e.g., 10 pF) NP0/C0G capacitors for temperature stability, placed within a few mm of the crystal pins with short, direct traces and a solid local ground return.

## Typical crystal oscillator circuit (in words)

The crystal's two terminals connect one each to the MCU's XTAL_IN and XTAL_OUT (or OSC_IN/OSC_OUT) pins. From each of those same two nodes, a load capacitor runs to ground — these are the two load capacitors whose parallel-series combination (per the CL formula) sets the crystal's effective load capacitance. No other components sit on this loop in the common case; some MCUs additionally specify a small series resistor between the amplifier output pin and the crystal to limit drive level, per that specific part's datasheet. The ground return for both load capacitors should tie into a solid, low-impedance ground area directly beneath or immediately adjacent to the crystal, ideally through short vias rather than a shared long trace with other ground returns, to keep the oscillator loop's reference quiet.

## Typical 2.4 GHz pi-matching network circuit (in words)

The RF IC's output pin connects first to a shunt capacitor to ground (the first element nearest the IC), then in series to an inductor, then to a second shunt capacitor to ground (nearest the antenna feed point), and finally to the antenna's feed pad — this is the classic pi topology (shunt-series-shunt). Component footprints are placed in this exact order along the RF trace, matching the vendor's reference layout, since swapping the order changes the network's effective response. The ground return for both shunt capacitors ties to the RF section's local ground pour, which itself connects back to the main board ground through the vendor-specified via pattern near the IC's own ground pins.

## Common mistakes

- Deviating from a chip/module antenna's reference layout (feed length, keepout, ground clearance) and getting a board that "connects" at close range but fails range/regulatory testing.
- Routing the RF feed trace through vias or long non-controlled-impedance runs, adding loss and reflections right where they matter most.
- Leaving a fast clock output unterminated because "it worked on the bench" — marginal termination often shows up only as intermittent EMI compliance failures or occasional bit errors under specific board loading/temperature.
- Modifying a certified RF module's antenna or matching section and assuming certification still applies — it doesn't, per nearly all modular certification grants.
- Placing CPWG side-ground stitching vias too sparsely, allowing unwanted propagation modes that weren't accounted for in the impedance calculation.
- Running digital switching traces or noisy power traces near/under the antenna keepout area, degrading RF performance in a way that's easy to miss without a spectrum analyzer.

## Schematic review checklist

- Crystal/oscillator choice (passive crystal vs active XO/TCXO) justified by the frequency accuracy/stability requirement of the interface it clocks.
- Clock buffer used (not a single output fanned to multiple loads directly) wherever more than one device needs a synchronized clock.
- RF section schematic matches the module/chip vendor's reference design, including matching network topology and component placeholders for tuning.
- Antenna feed and keepout requirements noted directly in the schematic or an attached layout note so they aren't lost by the time of layout.

## Layout review checklist

- Clock traces terminated per the buffer/receiver datasheet, length-matched where synchronization is required, routed away from crosstalk-sensitive nets.
- Antenna keepout area (ground clearance, component clearance) matches the antenna/module vendor's reference layout exactly — verified dimension by dimension, not eyeballed.
- RF feed trace is 50 Ω controlled impedance (or the module's specified impedance), short, via-free where possible.
- CPWG (if used) has correctly dimensioned side-ground gap and frequent stitching vias to the reference plane.
- Via fencing present and correctly spaced around RF-sensitive traces/sections if isolation or EMI suppression is required.
- No certified RF module's antenna/matching section has been altered from its reference layout.
