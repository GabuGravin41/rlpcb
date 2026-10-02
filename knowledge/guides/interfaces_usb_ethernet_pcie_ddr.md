---
title: Interface Design Rules — USB, Ethernet, PCIe, DDR, MIPI, HDMI, SerDes
domain: high-speed
tags: [USB, USB-C, Ethernet, PCIe, DDR, DDR3, DDR4, LPDDR4, MIPI, HDMI, SerDes, magnetics, refclk]
applies_to: [digital, high-speed, SoC, GPU/accelerator]
---

## USB 2.0

**Connections**: D+/D- differential pair from the transceiver (SoC/MCU internal PHY or discrete) to the connector, with a 90 Ω differential trace impedance. VBUS routed with appropriate current capacity (up to 500 mA on unconfigured/low-power, up to 900 mA–1.5 A+ depending on USB-IF power negotiation/BC1.2). ID pin (micro/mini) or CC pins (Type-C) used for role/power detection. Series termination resistors (typically ~22–33 Ω, check PHY datasheet) are sometimes integrated in the transceiver, sometimes required externally — verify against the specific PHY's datasheet.

**Layout rules**:
- 90 Ω differential impedance, length-matched intra-pair to a few mils.
- Keep D+/D- length under roughly 6 inches (150 mm) total from transceiver to connector for reliable USB 2.0 signal integrity on FR-4 without repeaters (informal industry guidance, not a hard spec number — shorter is always better).
- Add ESD protection (TVS diode array) as close to the connector as possible, before the trace runs across the board — this keeps ESD transients from coupling into other nets.
- Ferrite bead or common-mode choke on VBUS near the connector is common practice for EMI suppression, not universally mandatory.

## USB 3.x (SuperSpeed) and USB-C

**Connections**: Adds two SuperSpeed differential pairs (TX and RX, each 90 Ω) alongside the USB2 D+/D- pair. USB-C connector adds **CC1/CC2** pins, each requiring a pull-down resistor (5.1 kΩ to GND, per USB-IF spec) on the device/UFP side to signal "I am a USB-C device consuming power at default current," or a pull-up (current-source, typically ~56 kΩ/22 kΩ/10 kΩ selecting 500 mA/1.5 A/3 A per USB-IF Type-C spec) on the host/DFP side. A dedicated USB-PD/Type-C controller IC is the normal way to implement CC detection/negotiation correctly rather than hand-picking static resistors, especially if USB Power Delivery (voltages beyond 5 V) is needed.
- SBU1/SBU2 (sideband use, e.g., DisplayPort Alt Mode) and VCONN (powers cable e-marker chips in active/high-power cables) are additional Type-C signals to route if Alt Mode or higher-power PD is supported.

**Layout rules**:
- SuperSpeed TX/RX pairs: 90 Ω differential, AC-coupled per PHY vendor requirement (often on TX only, sometimes both — check datasheet), tightly length-matched intra-pair (≤5 mil typical).
- Keep SuperSpeed traces short and via-count minimal; every via adds discontinuity at multi-Gbps rates.
- USB-C connector receptacles often require both orientations (flippable) to be wired — either mirror TX/RX pairs to both pin sets (passive, doubles trace count) or use a re-driver/mux IC that detects orientation via CC and switches internally (common on mainstream designs since it saves board area and avoids a doubled fine-pitch differential escape).
- ESD array at the connector, on all exposed pins including CC and SBU.

## Ethernet (10/100/1000BASE-T)

**Connections**: MAC (in SoC/MCU) → PHY chip via MII/RMII/RGMII/SGMII depending on speed and pin budget → magnetics (integrated transformer, sometimes combined with the RJ45 jack as a "MagJack") → RJ45 connector. Four differential pairs (MDI0–MDI3) for Gigabit, two pairs for 10/100BASE-T. Each PHY needs a precision bias resistor (commonly 49.9 Ω 1%, check PHY datasheet) setting the line driver's reference current, plus a strapping/config resistor network on GPIO-shared pins that's read at reset for PHY address/mode.

**Layout rules**:
- 100 Ω differential impedance on all MDI pairs, matched intra-pair (~5 mil) and, ideally, pair-to-pair length reasonably close (tens of mil) though Gigabit's auto-negotiation and internal skew compensation is somewhat tolerant.
- Keep MDI traces away from noisy digital switching (SoC clocks, switching regulators) — Ethernet is baseband and very sensitive to coupled noise below its signal bandwidth.
- Magnetics placement: keep the trace run from PHY to transformer short and matched; the transformer provides galvanic isolation (typically 1500 Vrms per IEEE 802.3), so do not route a solid ground plane continuously underneath if isolation must be preserved — split the ground under/around the magnetics into "chassis/cable side" and "digital side" with a gap, bridged only by the required isolation components (magnetics, and for cable-side chassis ground, per Bob-Smith termination below).
- **Bob Smith termination**: a resistor network (commonly 75 Ω per leg to a common node, then a capacitor, typically ~1 nF/2 kV rated, to chassis ground) applied at the cable-side center taps of the magnetics to suppress common-mode noise and improve EMI compliance. It's debated because Gigabit's four active pairs make some PHY/magnetics combos not need it (2-pair 10/100 designs benefit more, since the unused pairs in a 4-pair cable can pick up noise without termination); check your PHY vendor's reference design — some explicitly recommend omitting it for Gigabit-only implementations with fully integrated magnetics.
- RJ45 shield, if present, should tie to chassis ground (not digital ground) typically through a low-value resistor or ferrite/direct connection per connector datasheet, again respecting the isolation barrier.

## PCIe

**Connections**: Each lane is a TX differential pair + RX differential pair (85 Ω nominal per PCI-SIG). A reference clock (REFCLK, 100 MHz typical, differential) is distributed from a clock generator/buffer to each device (or "SRIS/SRNS" clocking modes allow independent references in some newer implementations — check the specific generation's CEM spec). AC coupling caps (typically 100 nF) required in series on TX pairs. PERST# (reset), CLKREQ#, WAKE# and the SMBus/JTAG-ish sideband pins round out a typical PCIe endpoint connection along with power rails (often 3.3V aux, 3.3V/12V main per CEM slot spec for add-in cards).

**Layout rules**:
- 85 Ω differential (verify against PHY/controller vendor's guide; PCI-SIG base spec formally targets 85 Ω ±15% differential impedance for the interconnect).
- REFCLK must be matched in length between differential legs, and (for SRNS/common-clock topologies) matched in delay to other REFCLK outputs feeding multiple devices from the same clock source, per the clock buffer vendor's guide.
- **Lane polarity inversion**: PCIe explicitly allows TX+/TX- (and RX+/RX-) to be swapped at the physical layer, since the spec requires receivers to auto-detect and correct polarity — this is a deliberate escape valve for layout, letting you swap P/N assignment on a pair to simplify BGA escape without a "lane polarity" logic bug. **Lane-to-lane swap (reordering which lane goes where) is not universally supported** — check the specific controller before assuming lanes can be reordered; polarity inversion within a lane is safe, reordering across lanes generally is not.
- Keep TX and RX pairs on separate layers or well separated if on the same layer to minimize crosstalk between transmit and receive paths (NEXT/FEXT budget matters more as speed increases: Gen4/5 have much tighter loss and crosstalk budgets than Gen1/2).
- Evaluate via stub/back-drill needs for Gen3 (8 GT/s) and above.
- Length-match total trace length within a lane to keep skew low, and if possible match trace lengths across multiple lanes of a x4/x8/x16 link to simplify deskew, though PCIe's per-lane clock recovery makes this less critical than DDR fly-by matching.

## DDR3 / DDR4 / LPDDR4

**Connections**: SoC/controller memory interface → DRAM (discrete or DIMM/SODIMM, or point-to-point discrete DRAM for embedded designs). Includes: data (DQ) and data-strobe (DQS) pairs grouped per byte lane, address/command/control bus (shared across all DRAM devices in fly-by topology, or point-to-point per device in T-topology for small point-to-point systems), clock (CK/CK#) differential pair, VDD/VDDQ power, VREF reference voltage (DDR3; DDR4 moved VREF generation into each device, reducing board-level VREF routing needs), and ZQ calibration resistor (typically 240 Ω to ground on DDR3/DDR4 per JEDEC).

**Fly-by vs T-topology**:
- **T-topology** (older/lower-speed, DDR2 and slower DDR3 designs, or single-DRAM point-to-point): address/command/clock traces branch (stub) to each DRAM symmetrically from a T-junction. Simpler timing model but stubs limit achievable speed.
- **Fly-by topology** (standard for DDR3/DDR4 multi-drop, mandated by JEDEC for DIMMs): address/command/clock daisy-chains past each DRAM in sequence, each device tapping the bus with a short stub, terminated (VTT termination) at the far end. Requires **write-leveling** (the DRAM controller compensates for accumulated delay per device using training) — this is handled by the controller's memory training firmware, not by the PCB, but the PCB layout must support consistent, monotonic trace-length increase along the fly-by chain for that training to converge reliably.

**Byte-lane matching**: within each byte lane, match DQ/DM (data mask) lines to their DQS strobe pair tightly (commonly ±10–25 mil bit-level matching depending on DDR3 vs DDR4 and the vendor's spec — always pull the exact number from the SoC/memory controller's layout guide, they differ). Match length between byte lanes less tightly (byte-to-byte skew budget is looser because each byte lane has its own strobe for timing reference) but still bounded — some vendors define this in picoseconds rather than mils, especially for DDR4/LPDDR4 at high data rates.

**VTT termination**: fly-by topology terminates the address/command/control and (for DDR3, some DDR4 unbuffered configs) certain data lines at a **VTT rail = VDDQ/2** via a resistor (commonly 39–60 Ω into VTT, exact value from the reference design) at the end of the fly-by chain, sinking/sourcing termination current — needs a dedicated small VTT regulator or trench regulator near the termination resistors, not just a resistor divider (insufficient current capability). LPDDR4 typically simplifies this since many LPDDR4 designs use on-die termination (ODT) instead of board-level VTT, reducing external termination component count — check whether your specific LPDDR4 controller/DRAM combo relies on ODT alone.

**VREF**: DDR3 needs a board-routed VREF trace to both controller and DRAM, generated from VDDQ/2 with a resistor divider and decoupled with a capacitor at each device's VREF pin — treat VREF as a sensitive analog signal: short traces, generous decoupling, kept away from switching noise. DDR4 generates VREF internally per device (except for control/address VREF, which may still need board generation depending on the specific implementation) — check controller and DRAM datasheets.

**Layout rules (all DDR variants)**:
- Route address/command/control and each byte lane as tightly length-matched groups near the SoC and DRAM, minimizing via count and keeping the whole memory interface on as few layer transitions as possible.
- Keep DDR traces on stripline layers close to the SoC/DRAM BGA where possible to minimize crosstalk with other high-speed buses and reduce EMI.
- Maintain consistent trace impedance (documented target from your controller vendor, commonly 40–60 Ω SE / 80–100 Ω differential for clock/strobe) throughout — avoid width changes from BGA escape neckdowns propagating into the main route.
- Route decoupling for VDD/VDDQ with a mix of bulk and high-frequency caps distributed under/near the DRAM and SoC per the vendor's decoupling table, not guessed.
- Place ZQ calibration resistor close to its pin with a short, direct trace to ground.

## MIPI (CSI/DSI, camera/display interfaces)

**Connections**: Clock lane pair + one or more data lane pairs (D-PHY: differential pairs operating both in high-speed differential mode and low-power single-ended mode for control signalling — this dual-mode requirement makes MIPI layout more constrained than a pure differential interface).

**Layout rules**:
- 100 Ω differential nominal (check specific D-PHY/C-PHY spec revision — values can vary), tight intra-pair length matching (a few mil).
- Keep traces short (MIPI is typically used for short on-board or short-cable runs, often under a few inches to tens of cm depending on data rate and PHY spec version) — it is not designed for long-haul routing like PCIe/Ethernet.
- Avoid vias where possible; if unavoidable, keep symmetric on P/N.

## HDMI

**Connections**: Three TMDS differential data pairs + one TMDS clock pair, plus DDC (I2C-like, for EDID), CEC, hot-plug detect (HPD), and 5V/utility power to the connector.

**Layout rules**:
- 100 Ω differential TMDS pairs, matched intra-pair; keep pair-to-pair skew reasonably controlled (tens of ps) since all three data pairs + clock must arrive in sync for correct pixel decoding.
- AC coupling caps are typically on the source side per HDMI spec (source-terminated); sink is typically DC-coupled with on-chip termination — check your specific transmitter/receiver IC.
- ESD protection at the connector on all TMDS and control lines.

## SerDes (general)

**Connections**: Any high-speed differential TX/RX pair pattern (e.g., 1000BASE-KX, SFP+ electrical, JESD204B/C for data converters, custom SoC-to-SoC links) follows the same fundamentals as PCIe/USB3: AC coupling where the spec calls for it, matched differential impedance, minimized via/stub count.

**Layout rules**: apply the general high-speed SI rules from `high_speed_signal_integrity.md` — target impedance from the specific standard, length/skew matching, reference plane continuity, and an insertion-loss budget check against the qualified data rate.

## Power delivery considerations per interface

- **USB Power Delivery (USB-C PD)**: negotiating beyond 5V (9V/12V/15V/20V, and higher-current profiles under USB PD 3.1 Extended Power Range) requires a dedicated PD controller IC (or an MCU with PD stack firmware plus appropriate physical-layer support) handling the CC-line BMC (biphase mark coding) communication protocol — do not attempt to hand-roll PD negotiation with discrete logic; use a qualified PD controller and follow its reference design for the CC line's series resistor/protection network and VBUS switching (typically an external high-current load switch/FET controlled by the PD IC).
- **PCIe slot power**: CEM-compliant add-in cards draw power from the slot's 12V and 3.3V rails within the connector's per-pin current rating; cards needing power beyond the baseline slot allocation (common on GPU-class or accelerator add-in cards) require auxiliary power connectors, and the CEM spec defines specific power-negotiation signaling (e.g., presence-detect/power-limit pins) so the host system knows how much power the card intends to draw before enabling full power — respect this signaling in a custom PCIe add-in card design rather than assuming the slot will simply provide whatever the card asks for.
- **PoE (Power over Ethernet)**, where applicable to an Ethernet design, delivers DC power over the same cable pairs used for data (or dedicated spare pairs depending on PoE type) per IEEE 802.3af/at/bt, requiring a PoE PD (powered device) controller IC handling classification/negotiation and isolated DC-DC conversion — treat this as its own isolated power design (similar isolation-barrier discipline to the Ethernet magnetics isolation already described) layered on top of the standard Ethernet PHY/magnetics design.

## Protocol-level negotiation and link training (why layout enables it, doesn't replace it)

- PCIe, USB3, and DDR all rely on **link training** — an automatic negotiation/calibration sequence (equalization coefficients, clock recovery lock, in DDR's case write-leveling and read/write timing calibration) performed by the silicon at initialization to compensate for the actual channel's characteristics within its qualified range. Good layout (matched lengths, controlled impedance, adequate loss budget) exists to keep the channel within the range link training can successfully compensate for — link training is not a substitute for a well-designed channel, and a channel far outside spec can fail to train reliably even though the silicon "should" adapt.
- When debugging a link that won't train (PCIe link stuck at a lower-than-expected speed/width, USB3 falling back to USB2, DDR training failures reported by the SoC's boot log), suspect layout/SI issues (impedance mismatch, excessive skew, insertion loss, missing/misplaced AC caps) before assuming a pure silicon/firmware bug, especially if the issue is sensitive to temperature or specific board samples.

## Connector and cable considerations

- Connector selection itself is part of the signal integrity budget for every interface in this guide — a connector's own impedance discontinuity, crosstalk between adjacent pins, and rated bandwidth (some connectors are explicitly rated/qualified only up to a certain data rate) must be checked against the connector vendor's own high-speed datasheet/application data, not assumed adequate just because the pinout matches.
- For any interface routed to an external cable (Ethernet patch cable, USB cable, PCIe external cable in rare designs), remember that the cable and connector's contribution to the total channel loss/skew budget must be subtracted from what's available for the PCB itself — a marginal PCB design paired with a long or low-quality cable is a common field-failure combination that passes bench testing with a short, high-quality test cable.

## Quick reference: interface connection summary

| Interface | Key differential pairs | Key single/control signals |
|---|---|---|
| USB 2.0 | D+/D- (90 Ω) | VBUS, GND, ID (if micro/mini) |
| USB-C / USB3 | 2x SuperSpeed TX/RX (90 Ω), D+/D- | CC1/CC2, SBU1/2, VCONN, VBUS |
| Ethernet Gigabit | 4x MDI pairs (100 Ω) | Bias resistor, strap pins, LED signals |
| PCIe (per lane) | TX pair, RX pair (85 Ω) | REFCLK pair, PERST#, CLKREQ#, WAKE# |
| DDR3/DDR4 | CK/CK# (diff), DQS/DQS# per byte | DQ/DM, A/BA/cmd bus, VREF, ZQ, VTT |
| MIPI D-PHY | Clock pair + data lane pairs (100 Ω) | Low-power control mode (shared pins) |
| HDMI | 3x TMDS data + 1x TMDS clock (100 Ω) | DDC (I2C), CEC, HPD, +5V |

## Quick reference: AC coupling and termination by interface

| Interface | AC coupling | Termination |
|---|---|---|
| PCIe TX | Yes, ~100 nF, per CEM spec | On-die (receiver) |
| USB3 SuperSpeed | Per PHY vendor (often TX) | On-die |
| DDR fly-by address/command | N/A (DC) | VTT = VDDQ/2 at chain end |
| DDR ODT (LPDDR4 typical) | N/A | On-die termination, no board VTT |
| HDMI TMDS | Source-side typical | On-die (sink) |
| Ethernet MDI | N/A (transformer-coupled) | Internal to PHY, Bob Smith optional |

## Quick reference: USB-C CC resistor roles (UFP/DFP)

| Role | CC configuration | Meaning |
|---|---|---|
| UFP (device) | 5.1 kΩ pull-down each CC | Signals device presence, default current |
| DFP (host), default | ~56 kΩ pull-up | Offers 500 mA/900 mA (spec-dependent) |
| DFP (host), 1.5 A | ~22 kΩ pull-up | Offers 1.5 A |
| DFP (host), 3 A | ~10 kΩ pull-up | Offers 3 A |

Values are illustrative per USB-IF Type-C spec convention; use a certified Type-C/PD controller IC rather than hand-picking resistors for any design needing correct, robust negotiation.

## Typical Ethernet PHY-to-RJ45 circuit (in words)

The PHY chip's four MDI differential pin pairs each connect through length- and impedance-matched trace pairs directly to the primary-side windings of an integrated magnetics module (transformer plus common-mode choke, often combined with the RJ45 jack as a single "MagJack" part). The magnetics' secondary-side (cable-side) windings connect to the RJ45 jack's contact pins, which mate with the Ethernet cable. A center-tap on each secondary winding (if Bob Smith termination is implemented) connects through a resistor to a common node, which then connects through a single capacitor to chassis ground — this provides a common-mode noise path to chassis without creating a DC path across the isolation barrier. The PHY's bias-setting pin connects through a precision resistor (value per datasheet, commonly ~49.9 Ω) to ground, setting the PHY's internal current reference. PHY strapping pins (read at reset to set PHY address and default mode) each connect through a resistor to either VDD or ground per the desired default configuration, chosen so an external device connected to the same physical pins for another purpose during normal operation doesn't conflict with the reset-time strap reading.

## Typical PCIe REFCLK distribution circuit (in words)

A clock generator/buffer IC's differential REFCLK output pair connects through matched-length, 100 Ω-class (check buffer datasheet; PCIe REFCLK impedance target may differ slightly from the 85 Ω data-lane target) differential traces to each downstream device's REFCLK input pair — in a common-clock (SRNS/SRIS-agnostic simple) topology, every device shares outputs from the same buffer, with trace lengths matched not just within each pair but across all the buffer's REFCLK outputs feeding devices that must share timing reference. Each REFCLK trace typically has a small series or AC-coupling component per the buffer/receiver's specific requirement (check datasheet — some REFCLK architectures are DC-coupled, unlike the data lanes which are always AC-coupled). The buffer's own reference (crystal or input reference clock) and power supply are decoupled and laid out following the same crystal/clock-buffer guidance described in `clocks_and_rf_basics.md`.

## Common mistakes

- Treating CC pull-down/pull-up resistor values on USB-C as arbitrary — wrong values misrepresent current capability to the other end and can cause under/over-current situations; use a proper Type-C controller for anything beyond basic 5V/500mA.
- Continuous ground plane bridging Ethernet's isolation barrier, defeating the transformer's galvanic isolation and risking safety/EMI compliance failure.
- Assuming PCIe lanes can be freely reordered on a connector — only polarity (P/N) swap within a lane is guaranteed safe; verify lane-reorder support with the specific controller.
- Ignoring fly-by topology's requirement for monotonically increasing trace length along the chain, which breaks the controller's write-leveling training.
- Skipping VTT/VREF decoupling on DDR, causing marginal timing that only shows up as intermittent memory errors under temperature/voltage corners.
- Routing MIPI or other short-reach differential pairs like a long PCIe trace with multiple vias, exceeding the PHY's loss budget for links that were never designed for long runs.

## Schematic review checklist

- USB-C: CC1/CC2 pull resistors (or dedicated PD controller) present and correctly valued per USB-IF Type-C spec for the intended power role.
- Ethernet PHY: bias resistor value matches datasheet; strapping resistors for PHY address/mode present; magnetics isolation barrier clearly shown with chassis vs digital ground separation.
- PCIe: AC coupling caps present on TX pairs (per controller vendor), REFCLK distribution shown with correct termination, PERST#/CLKREQ# wired per CEM spec.
- DDR: VTT regulator and termination resistors present for fly-by nets requiring them; VREF generation (if needed) shown with divider + decoupling; ZQ resistor present.
- All differential pairs named with consistent P/N suffixes for KiCad auto-recognition.

## Layout review checklist

- Target impedance for every interface confirmed against this guide's values (or the specific vendor spec where it differs) and matched to net class definitions.
- Ethernet ground split under magnetics preserved (no accidental plane fill bridging it); Bob Smith termination included or knowingly omitted per PHY vendor guidance.
- PCIe REFCLK length-matched; AC caps placed symmetrically close to TX driver; via stub/back-drill evaluated for Gen3+.
- DDR fly-by address/command/clock trace lengths increase monotonically along the chain; byte-lane DQ/DQS matched to vendor's tolerance; VTT/VREF traces short and well-decoupled.
- USB-C orientation handling (mirrored pairs or redriver/mux) implemented and verified against connector pinout.
- No high-speed interface trace crosses a plane split, isolation gap (other than Ethernet's intended isolation barrier), or unrelated antenna/RF keepout.
