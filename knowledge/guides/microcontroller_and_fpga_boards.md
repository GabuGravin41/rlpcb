---
title: Microcontroller and FPGA Minimum System Design
domain: digital
tags: [MCU, STM32, ESP32, RP2040, ATmega, FPGA, crystal, decoupling, SWD, JTAG, bootloader, power-sequencing]
applies_to: [digital, MCU, FPGA]
---

## MCU minimum system — power

- Every power pin (VDD/VDDIO/VDDA/VBAT/VCAP, etc.) must be connected — MCUs commonly have multiple VDD pins distributed around the package specifically to reduce IR drop and inductance to internal circuit blocks; do not tie only one and leave others floating, even if internally they connect to the same rail.
- **VDDA/VREF (analog supply/reference)**: filter separately from digital VDD even if nominally the same voltage — typical practice is a ferrite bead or small-value resistor (a few ohms) from digital VDD to VDDA, plus its own local decoupling (e.g., 100 nF + 1 µF), to keep digital switching noise out of the ADC/analog reference.
- **VCAP/VDD_CORE** (internal LDO output on many MCUs, e.g., STM32 VCAP pins): needs the exact capacitor value and placement the datasheet specifies (commonly 1 µF or 2.2 µF, X5R/X7R ceramic) — this is the internal core regulator's output filter, not a general-purpose decoupling cap, and using the wrong value can affect internal LDO stability.
- **VBAT** (RTC/backup domain): if unused for battery backup, tie to VDD per datasheet guidance rather than leaving floating.

## Decoupling

- Standard practice: one 100 nF (X7R ceramic) capacitor per VDD pin, placed as close as physically possible to the pin (ideally within ~2 mm, directly adjacent, with a short via to plane rather than a long trace) — this is a well-established convention, not a datasheet-specific number, but always check the vendor's application note for exact recommended values, since some MCUs also want a bulk cap (1–10 µF) per power domain in addition to the per-pin 100 nF.
- Route the decoupling cap's ground connection through a short via directly to the ground plane; a long, thin trace to the via defeats the low-inductance purpose of local decoupling.
- Place bulk capacitors (1–10 µF, sometimes larger for high-transient loads) near the regulator output feeding the MCU and/or distributed among the per-pin caps for larger packages.

## Reset

- **NRST/RESET pin**: typically has an internal weak pull-up in modern MCUs, but adding an external decoupling capacitor (commonly 100 nF) improves noise immunity against brief glitches; check whether the datasheet recommends an external pull-up too (some parts explicitly warn against adding extra capacitance beyond a small value because it can interact with internal reset-filtering circuitry — always confirm against the specific datasheet before adding a cap you weren't told to add).
- A manual reset button (normally-open switch to ground) in parallel with the cap is common for development/debug boards.

## Boot pins

- Many MCUs (STM32 BOOT0, ESP32 GPIO0/strapping pins, etc.) sample a boot-mode-select pin at reset to decide whether to run from flash or enter a bootloader (UART/USB DFU/etc.).
- Tie boot-select pins to a definite level (pull-up or pull-down, per the desired default boot mode) through a resistor (commonly 10 kΩ) rather than leaving floating, and if a button/jumper is provided to force bootloader mode for field firmware recovery, make sure the resistor is weak enough that the button can override it reliably.
- ESP32-class parts have multiple strapping pins (GPIO0, GPIO2, GPIO12/MTDI, GPIO15/MTDO on many variants) that affect boot mode and flash voltage — check the specific module/chip datasheet's strapping table before assigning these pins to other functions, since a peripheral pulling a strapping pin the wrong way at reset can prevent boot entirely.

## Crystal oscillator design and load capacitance

A crystal needs two load capacitors (one per pin to ground) sized so the crystal sees its specified load capacitance (CL, from the crystal's datasheet, commonly 6–20 pF for MCU crystals).

**Formula**:
```
CL = (C1 * C2) / (C1 + C2) + Cstray
```
Where C1, C2 are the two external load capacitors (commonly chosen equal, C1 = C2), and Cstray is the parasitic capacitance from PCB traces, the MCU's pin capacitance, and package — typically estimated around 2–5 pF total unless the MCU datasheet gives a specific pin capacitance figure.

**Worked approach**: for a crystal specifying CL = 12 pF, with an estimated Cstray of 3 pF and choosing C1 = C2 = C:
```
12 = (C*C)/(2C) + 3  →  9 = C/2  →  C = 18 pF
```
So two 18 pF (or nearest standard value, e.g., 18 pF or 20 pF) capacitors would be selected, then ideally verified/tuned against actual oscillation and frequency accuracy if precision matters (some designs measure actual frequency and adjust C1/C2 slightly to null out frequency error — relevant for USB/Ethernet timing-critical crystals where clock accuracy tolerance is tight).

**Layout rules**:
- Keep the crystal and both load caps as close to the MCU's oscillator pins as possible, with short, direct traces — the oscillator loop is high-impedance and sensitive to parasitic capacitance and coupled noise.
- Route a ground plane or guard trace around/under the crystal and its caps, and avoid routing switching digital signals underneath or immediately adjacent to the crystal — crosstalk here can cause frequency instability or failure to start oscillating.
- Do not run the crystal's traces near VDD/VDDA planes edges or noisy nets; keep the loop area small.
- Many MCU vendors publish a specific crystal layout app note (e.g., ST AN2867 for STM32) — follow it when available rather than generic rules alone.

## SWD / JTAG

- **SWD** (2-wire: SWDIO + SWCLK, plus VDD reference and GND, and usually NRST) is the compact standard for ARM Cortex-M debug; **JTAG** (TDI/TDO/TCK/TMS, plus TRST optional) is used where more pins are available or for boundary-scan/FPGA use.
- Provide a standard debug header footprint (common ones: ARM 10-pin 0.05", Tag-Connect footprints for space-constrained boards) matching your debug probe.
- Keep debug traces short and away from noisy high-speed signals; add series resistors (commonly 22–100 Ω) on SWCLK/SWDIO if signal integrity issues are seen at higher debug clock speeds, though this isn't always necessary for short traces.
- Pull SWDIO/SWCLK to a defined level per the MCU's recommendation if the debug port shares pins with GPIO that must have a known state before a debugger attaches.

## USB bootloaders and field firmware

- If using USB DFU or a UART-based bootloader for field updates, ensure the boot-mode-select mechanism (button, jumper, or software-triggered via a magic value in RAM/flash) is accessible without needing SWD/JTAG hardware, so end users or field technicians can recover/update firmware.
- Provide a way to force bootloader entry independent of application firmware health (e.g., hold a button at power-up) so a bad firmware update cannot brick the board.

## FPGA power sequencing

- FPGAs (Xilinx/AMD, Intel/Altera, Lattice, etc.) commonly have multiple voltage rails: **VCCINT** (core logic, low voltage, needs tight tolerance and often significant current for larger devices), **VCCAUX** (auxiliary, supports internal features like configuration and some I/O circuitry), and one **VCCO per I/O bank** (bank voltage, sets the I/O standard voltage for that bank — commonly 1.2–3.3V depending on which I/O standard the bank's pins use).
- **Power sequencing requirements are device-family-specific** — many parts require VCCINT to be at or before VCCAUX, or specify a maximum allowed delay between rails reaching their thresholds; violating the vendor's specified sequencing can cause excess current draw, configuration failure, or in the worst case device stress. Always pull the exact sequencing requirement from the specific FPGA family's power management user guide rather than assuming a generic order — this varies by vendor and family generation.
- Implement sequencing with a dedicated power-sequencer IC, a supervisory/sequencing-capable PMIC, or discrete supervisory logic (comparators/delay circuits) — do not rely on "it happened to power up close enough together" without a designed sequencing mechanism, since supply ramp rates vary board to board and over temperature.

## FPGA bank VCCO

- Each I/O bank's VCCO must match the I/O standard(s) assigned to pins in that bank (e.g., LVCMOS33 pins need a 3.3V bank, LVDS pins typically need a specific bank voltage per the family's I/O standard table) — assign pins to banks in the vendor's design tool (or plan it manually before schematic capture) so that no bank is asked to support two I/O standards needing different VCCO simultaneously.
- Decouple each bank's VCCO locally, similar to MCU VDD decoupling practice, since I/O switching current can be significant, especially for banks driving many high-speed or high-current I/O.

## FPGA configuration flash and clocking

- Most FPGAs load their configuration bitstream at power-up from an external **configuration flash** (SPI flash is common for many modern FPGA families) or are configured by an external controller/JTAG — choose the configuration mode per the family's configuration guide and wire the corresponding mode-select pins to fixed levels.
- Provide a way to reprogram the configuration flash in-system (via JTAG, or via the FPGA's own configuration interface in a pass-through mode) so firmware/bitstream updates don't require desoldering the flash chip.
- **Clocking**: FPGAs typically need at least one reference clock into a dedicated clock-capable input pin (feeding internal PLLs/MMCMs) — check the family's clock-input pin restrictions (not every pin can serve as a clock input) and route that clock trace with the same care as any other high-speed clock (short, controlled impedance if frequency warrants it, minimal crosstalk exposure).

## Power supply sequencing and brownout for MCUs

- Most modern MCUs include an internal brownout detector (BOR/POR) that holds the device in reset until supply voltage crosses a defined threshold, and re-asserts reset if supply droops below it during operation — check the specific threshold against your regulator's actual output tolerance and ripple, since a marginal regulator right at the BOR threshold can cause intermittent resets that look like a firmware bug.
- For MCUs with multiple rails (e.g., a core rail from an internal LDO plus an external VDDIO), confirm whether the vendor specifies a required power-up order or timing window between rails — many simple MCUs tolerate any order, but some (particularly ones with a separate analog rail or an external core-voltage regulator) do have sequencing requirements documented in the datasheet's power-up section; don't assume no requirement exists without checking.

## GPIO drive strength, pull configuration, and unused pins

- Configure GPIO drive strength (where the MCU offers selectable drive strength) appropriately for the load — over-driving a lightly loaded net wastes power and can increase EMI from unnecessarily fast edge rates on GPIO not requiring it (e.g., a simple LED driver doesn't need the fastest available slew rate).
- Leave truly unused GPIO pins in a defined state (internal pull-up or pull-down enabled in firmware/configuration, or tied externally on power-sensitive/boundary-scan-relevant designs) rather than floating, to avoid unnecessary leakage current or noise-induced toggling that can contribute to EMI or minor power draw in low-power designs.
- For pins shared between GPIO and a boot-strapping/special function (common on ESP32/RP2040-class parts), document clearly in the schematic which pins are "reserved by hardware function" so firmware/board-bring-up doesn't accidentally reassign a strapping pin to a conflicting peripheral function.

## RP2040 and similar external-flash-boot MCUs

- Parts like the RP2040 boot from external QSPI flash rather than internal flash — the flash chip's connection (CLK, CS, and 1–4 data lines depending on SPI/dual/quad mode) must meet the vendor's specified maximum trace length and impedance guidance at the chip's boot QSPI clock rate, since this bus runs at first-boot time before any application configuration can adjust timing.
- A crystal is typically required (rather than relying on an internal RC oscillator alone) when precise USB timing is needed, per the specific chip's clocking architecture — check whether the target MCU's internal oscillator is USB-certified-accurate on its own or requires an external crystal reference.

## ESP32-class module integration

- When using a pre-certified Wi-Fi/BLE module (as opposed to a raw chip design), follow the module vendor's recommended power supply decoupling and current capability (RF TX bursts can draw several hundred mA momentarily, as discussed in `clocks_and_rf_basics.md`) — undersized regulator/decoupling on the module's 3.3V input is a very common cause of random resets/brownouts correlated with Wi-Fi activity on hobbyist designs.
- Respect the module's antenna keepout area exactly as specified in its integration guide (see `clocks_and_rf_basics.md`) to preserve both RF performance and, where relevant, the module's regulatory certification.

## Watchdog timers

- Enable and correctly configure an independent/windowed watchdog timer in firmware for any product expected to run unattended — the watchdog periodically requires firmware to "kick" it within a timeout window, and resets the MCU if firmware hangs (e.g., stuck in an unexpected state or infinite loop), providing a basic recovery mechanism from software faults without requiring board-level design changes.
- Some MCUs offer an independent watchdog clocked from a separate internal oscillator (immune to a main-clock failure) versus a windowed watchdog tied to the main system clock — understand which your target part offers and choose based on the fault modes you need covered.

## Quick reference: typical MCU minimum-system components

| Function | Typical component | Notes |
|---|---|---|
| Per-VDD decoupling | 100 nF X7R ceramic | One per VDD pin, placed within ~2 mm |
| Bulk decoupling | 1–10 µF ceramic/tantalum | Near regulator output/power entry |
| VCAP (internal LDO) | 1–2.2 µF ceramic | Exact value per datasheet, not generic |
| NRST filtering | 100 nF (if datasheet allows) | Check datasheet before adding |
| Boot-select pull | 10 kΩ | Pull to definite level, allow override |
| Crystal load caps | 10–22 pF (per CL calc) | NP0/C0G for stability |
| SWD series resistor (optional) | 22–100 Ω | Only if signal integrity issues seen |
| Watchdog timeout | Application-dependent | Independent osc. preferred for fault coverage |

## Quick reference: FPGA rail overview

| Rail | Typical voltage range | Purpose |
|---|---|---|
| VCCINT | 0.85–1.2 V (family-dependent) | Core logic fabric |
| VCCAUX | 1.8–2.5 V (family-dependent) | Auxiliary/config circuitry |
| VCCO (per bank) | 1.2–3.3 V (I/O standard dependent) | I/O bank driver voltage |
| VCCBRAM (some families) | Similar to VCCINT | Block RAM supply, family-specific |

## Worked example: crystal load cap for an 8 MHz MCU crystal

Datasheet CL = 10 pF, estimated Cstray = 2 pF (no pin-capacitance figure given, conservative default assumption):

```
10 = C/2 + 2
8 = C/2
C = 16 pF
```

Select two 15 pF or 18 pF (nearest standard values) NP0/C0G capacitors; if precise frequency accuracy matters (e.g., feeding a UART baud rate or timing-critical peripheral), measure actual oscillation frequency on a populated board and adjust C1/C2 slightly if trimming is warranted.

## Typical MCU minimum-system circuit (in words)

Each VDD pin on the MCU connects to the 3.3V (or applicable) supply rail, with a 100 nF ceramic capacitor placed immediately adjacent to that pin, its other terminal returning to ground through a short via. The VDDA pin connects to the same 3.3V rail but through a small-value resistor or ferrite bead, with its own local 100 nF plus a larger bulk capacitor (e.g., 1 µF) to ground, isolating it from digital switching noise on the main VDD rail. The VCAP pin (internal core regulator output, where present) connects only to its datasheet-specified capacitor value to ground — no other connection. NRST connects to a pull-up (often internal, sometimes needing an external one per datasheet) and, where the datasheet allows, a small decoupling capacitor to ground; a normally-open push-button in parallel with that capacitor, its other terminal to ground, provides manual reset. The BOOT0 (or equivalent) pin connects through a 10 kΩ resistor to ground (for default boot-from-flash) or to VDD (for default boot-to-bootloader), with a jumper or button able to override the resistor's pull for field bootloader entry. The crystal connects across the two oscillator pins, with a load capacitor from each oscillator pin to ground per the CL calculation. The SWD header's SWDIO and SWCLK pins connect directly to the MCU's corresponding debug pins, with the header's VDD pin tied to the MCU's supply rail (so the debug probe can sense target voltage) and GND tied to system ground.

## Typical FPGA power sequencing circuit (in words)

A sequencer/supervisor IC monitors each rail's voltage through a resistor-divider or direct-sense input (VCCINT, VCCAUX, and each active VCCO bank) and drives each rail's regulator enable pin in the vendor-specified order, inserting the required delay between each enable assertion per the FPGA family's power-up sequencing specification. Each regulator's power-good output feeds back into the sequencer as a confirmation that a given rail has actually reached its threshold before the sequencer proceeds to enable the next rail in the chain — sequencing on a fixed timer alone without power-good feedback risks proceeding to the next rail before the previous one has actually stabilized, especially under load or cold-start conditions. On power-down, the sequencer (if it manages power-down ordering too, per the family's requirement) reverses the enable order, and a common overall system reset/config-done signal from the FPGA itself confirms successful configuration once all rails are stable and the bitstream has loaded.

## Common mistakes

- Leaving an unused VBAT or auxiliary power pin floating instead of tying it per datasheet guidance.
- Adding an "extra" capacitor on NRST or other pins the datasheet warns against, based on generic MCU decoupling habit rather than checking the specific part.
- Miscalculating crystal load capacitors by forgetting to subtract/account for stray capacitance, resulting in frequency offset from nominal.
- Leaving boot-select/strapping pins floating or letting another peripheral pull them the wrong way at reset.
- No accessible way to force bootloader entry, bricking boards in the field after a bad firmware update.
- Assuming all FPGA rails can ramp "whenever" without checking the family's sequencing spec, causing intermittent configuration failures.
- Mixing I/O standards needing different VCCO within the same FPGA bank.

## Schematic review checklist

- Every power pin (including VBAT, VCAP, VDDA, and any auxiliary rails) is connected per datasheet, none floating without an explicit justification.
- Decoupling caps present on every VDD pin, values checked against the vendor's app note (not just a blanket 100 nF assumption where the datasheet specifies otherwise).
- Crystal load capacitors calculated from CL, and crystal specified with correct CL, ESR, and frequency tolerance for the application (tighter for USB/Ethernet timing than for a simple UART baud clock).
- Boot-select/strapping pins pulled to a defined default state with resistor values appropriate to allow override by a button/jumper if provided.
- SWD/JTAG header present with standard pinout, and NRST/BOOT accessible from the header or a dedicated button for recovery.
- FPGA: bank-to-I/O-standard assignment checked for consistency before finalizing schematic; power sequencing mechanism explicitly shown, not implied.

## Layout review checklist

- Decoupling caps placed within a couple mm of their pins with short via-to-plane ground connections, not routed through long traces.
- Crystal and load caps placed tight to the oscillator pins, ground-guarded, away from switching digital nets.
- VDDA/analog supply filtered from digital VDD with the specified ferrite/resistor and local decoupling, analog ground area kept quiet.
- FPGA VCCINT/VCCAUX/VCCO planes sized and decoupled per the family's power design guide; sequencing IC or logic laid out with clear, short connections to its sensed rails.
- Configuration flash and JTAG/SWD accessible without needing to desolder components for firmware recovery.
- Clock input traces to FPGA/MCU routed short and away from noisy switching regulators or high-current traces.
