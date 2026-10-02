---
title: BGA Fanout and GPU/Accelerator-Class Board Architecture
domain: high-speed
tags: [BGA, fanout, escape-routing, HDI, VRM, multiphase, power-delivery, GPU, accelerator, OAM, PCIe-CEM]
applies_to: [BGA, GPU/accelerator, HDI, high-current power]
---

## BGA fanout basics

**Dog-bone fanout**: a short trace ("dog bone") pulls each ball out to a via placed just outside the pad, in the gap between balls, so the via — not the pad itself — carries the signal to inner/outer layers. Standard technique down to about 0.5 mm pitch; below that, via size and drill tolerance leave too little clearance between adjacent dog-bone vias.

**Via-in-pad**: the via is placed directly inside the BGA pad. Required once pitch is tight enough (typically ≤0.5 mm, always at 0.4 mm) that a via cannot fit in the gap between pads without violating annular ring or spacing rules. Via-in-pad must be filled (typically epoxy-filled) and plated/capped over per IPC-4761 (commonly Type VII: filled and capped both sides) so it presents a flat, solderable surface — an unfilled via-in-pad wicks solder paste into the barrel during reflow, causing voids and weak/open joints. This is a real, common defect on hobbyist-run fine-pitch boards that skip the "via fill" fab option to save cost.

## Escape routing by pitch

- **1.0 mm pitch**: 1–2 routing layers typically sufficient; standard dog-bone with through-hole vias; easy on any prototype fab.
- **0.8 mm pitch**: dog-bone still workable; 2–4 layers depending on ball count; through-hole vias usually fine if drill/annular-ring rules are respected (need roughly 0.2 mm minimum via pad clearance from adjacent structures at this pitch).
- **0.65 mm pitch**: dog-bone workable for outer 1–2 rows; inner rows often need blind vias or a via slightly smaller than standard through-hole; 4–6 layers typical; start considering HDI if ball count is high (>300–400).
- **0.5 mm pitch**: microvias generally required to escape inner rows; via-in-pad common; 6–10+ layers; this is the threshold where "regular" prototype fab processes become marginal and an explicit HDI order is usually needed.
- **0.4 mm pitch (and below)**: any-layer HDI, via-in-pad mandatory across most/all balls, stacked or staggered microvias, 10–20+ layers typical for high ball-count parts. This tier is standard for mobile SoCs and high-end FPGAs/accelerators and is generally beyond hobby-fab capability without an HDI-capable, higher-cost fab and correspondingly higher NRE.

**Layer count estimate rule of thumb**: count the number of ball rows that cannot be dog-boned on the outer 1–2 layers (i.e., interior rows surrounded on all sides by other balls). Each additional "ring" of interior balls generally requires roughly one more escape/routing layer pair, on top of whatever base layer count the rest of the board's interfaces already demand (see `stackup_and_layer_count.md`).

## GPU/accelerator-class board architecture (conceptual overview)

This section describes the architecture of large accelerator/GPU boards (data-center GPU cards, AI accelerator boards) at a conceptual level — the level a hobbyist should understand to reason about such boards, not a fabrication-ready design. These boards are firmly in the "12–26+ layer HDI, expensive fab, six-to-seven-figure NRE for the silicon/package itself" category; no part of this section should be read as "buildable at JLCPCB-class prototyping cost."

### Multiphase VRM for the core rail

The GPU/accelerator die's core voltage rail draws very high current (hundreds of amps is routine for large accelerator dies) at low voltage (often well under 1V), which a single regulator stage cannot deliver efficiently or with adequate transient response. The standard solution is a **multiphase buck converter**:

- A **multiphase PWM controller** (a single IC) generates interleaved PWM signals for many phases (12, 16, 20, or more phases is common on the largest accelerator boards), each phase offset in switching timing so their combined output ripple partially cancels and the input capacitor sees much lower RMS ripple current than a single-phase design would.
- Each phase drives a **smart power stage** (an integrated MOSFET half-bridge + gate driver in one package, often communicating current/temperature telemetry back to the controller) rather than discrete high-side/low-side MOSFETs + separate gate driver — smart power stages simplify layout (fewer discrete parts, tighter loop) and improve current sharing accuracy between phases.
- The controller typically communicates over **PMBus** (I2C-based power management protocol) with the board management controller/BMC for voltage margining, telemetry (current, temperature, fault status), and sequencing coordination.
- Each phase's inductor and output capacitance is placed close to its power stage; output capacitance (many bulk + many ceramic caps) is distributed around the die's power delivery footprint, not concentrated in one spot, to minimize the loop inductance seen by fast load-transient current from the die.

### Power planes and via arrays for hundreds of amps

- Core rail current in the hundreds of amps cannot be carried by a single trace or even a single plane layer at reasonable copper weight — designs use **multiple parallel plane layers** for the same rail, tied together with **dense via arrays** (via stitching, sometimes hundreds to low thousands of vias) directly under and around the die's power balls to spread current across all parallel planes and minimize both DC resistance (IR drop) and inductance.
- IR drop budget: the die's core voltage tolerance (often a few percent of an already-low voltage) leaves very little margin, so plane resistance from VRM output to die must be calculated (or simulated with a power-integrity/DC-drop tool) rather than assumed — this is standard practice on this class of board and generally requires PDN (power delivery network) simulation software, not hand calculation alone.
- Return current (ground) needs equally dense via stitching adjacent to every power via to keep loop inductance low for the die's fast transient current steps.

### Socket/mezzanine and connector concepts

- **OAM (OCP Accelerator Module) / SXM-style modules** (conceptual pattern, not a specific vendor's proprietary pinout): an accelerator module plugs into a baseboard via a high-density, high-speed mezzanine connector carrying power, PCIe/NVLink-class interconnect, and management signals — this lets multiple accelerator modules share a common baseboard power/interconnect fabric in a server chassis.
- **PCIe CEM (card electromechanical) form factor**: the standard add-in-card edge connector (as used by consumer/workstation GPUs) — a card-edge connector carrying PCIe lanes, power (12V/3.3V rails per CEM spec, with higher-power cards using auxiliary power connectors beyond slot power), and sideband/management signals, plugging into a standard PCIe slot.
- Both approaches route very-high-speed differential pairs (PCIe Gen4/5, or vendor-proprietary NVLink/interconnect-class SerDes) through the connector — connector selection and its own impedance/crosstalk characteristics become part of the signal integrity budget, verified against the connector vendor's own impedance/loss data.

### Thermal and mechanical considerations

- **Stiffeners**: a metal (often stainless steel or aluminum) frame bonded around/near the die package to prevent PCB warp under the heavy heatsink/cold-plate clamping force and to protect the die package edges from cracking during handling and thermal cycling.
- **Backplates**: a metal plate on the opposite side of the board from the heatsink, both for additional stiffness (counteracting the heatsink's clamping load) and for some secondary heat spreading from board-side components (e.g., memory, VRM inductors).
- Heatsink/cold-plate clamping pressure must be reacted by the stiffener/backplate structure, not by the PCB alone — PCB laminate is not designed to be a structural clamping surface under multi-kilogram cooler loads.

### HBM is on-package — you don't route it

High Bandwidth Memory (HBM) stacks are attached to the accelerator die on an **interposer inside the package** (silicon or organic interposer performing extremely fine-pitch, extremely short die-to-die routing that no PCB process can achieve). As a board designer, **you never see or route HBM signals** — they never leave the package. The PCB only sees the package's external BGA balls, which carry the die's external interfaces (PCIe/interconnect, management, and the shared power/ground network) — HBM's multi-thousand-bit-wide interface stays entirely inside the package. This is a hard boundary: no amount of PCB layer count or HDI capability substitutes for package-level interposer routing, and no hobbyist PCB process could achieve the pitch (tens of micrometers) HBM interconnect requires even if it wanted to.

### Board-level bring-up

- **Power sequencing**: rails must power up (and down) in a specific order and within specific timing windows relative to each other (e.g., core rail before I/O rail, or vice versa, per the die vendor's power sequencing requirement) — implemented via sequencer ICs, PMBus-programmable controller sequencing, or supervisory logic in a CPLD/BMC. Violating sequencing can latch up or damage the die.
- **Monitoring**: voltage, current, and temperature telemetry (via PMBus, I2C sensors, or the VRM controller's built-in telemetry) feeds a board management controller that can throttle or shut down the board on a fault (overcurrent, overtemperature, undervoltage) before damage occurs.
- **Bring-up practice**: first power-up of a new high-current board is normally done through a current-limited bench supply with sequencing verified at low voltage/current before applying full rails, and rails are checked one at a time with a scope for overshoot/ringing before the die is populated or powered, when practical.

## Decoupling strategy for large BGA power domains

- A large accelerator/SoC BGA typically has hundreds of dedicated decoupling capacitor placements around its perimeter and underneath (on the opposite side of the board, back-drilled or via-connected up through the plane stack) organized by frequency role: bulk capacitance (hundreds to thousands of µF, often polymer/tantalum, placed near the VRM output) handles low-frequency load transients; mid-range ceramic capacitance (tens of µF total, 0805/0603-class parts) handles the mid-frequency gap; small high-frequency ceramics (0402/0201-class, placed as close as physically possible to the BGA power/ground ball pairs) handle the fastest edge-rate transients the VRM's control loop can't react to in time.
- The goal is a flat **target impedance** for the power delivery network (PDN) across the frequency range the die's transient current steps span — this is normally derived from the die vendor's PDN target impedance specification (Ztarget = allowed voltage ripple / maximum transient current step) and verified with a PDN impedance simulation tool, not just "add lots of caps and hope."
- Capacitor **mounting inductance** (via placement relative to the pad, via count per cap) matters more than raw capacitance value at high frequency — use two vias per capacitor pad (one per terminal) placed as close to the pad as possible, and prefer multiple smaller capacitors in parallel over one larger one when minimizing loop inductance is the goal, since multiple parallel vias reduce effective inductance.

## Interposer/substrate awareness (package-level context)

- The accelerator/GPU **package substrate** (a small, extremely fine-pitch multilayer laminate or silicon interposer inside the chip package itself, distinct from the PCB) is where the die's power/ground network fans out from die-level micro-bump pitch to the package's external BGA ball pitch, and where HBM die-to-die routing happens entirely. The board designer's job starts at the package's external BGA balls — everything inside the package (interposer routing, die-to-die HBM channels, on-package decoupling capacitors embedded in the substrate) is the silicon/package vendor's domain, delivered as a fixed BGA footprint with a power/ground/signal ball map in the vendor's package datasheet.
- Some accelerator packages include **on-package decoupling** (small capacitors mounted directly on the package substrate, inside the package outline) specifically to handle the very fastest transient edges before the board's own decoupling network can respond — the board's job is still to provide a low-inductance path for the next tier of response (the fast board-level ceramic caps described above).

## Testing and bring-up instrumentation for high-current boards

- Provide **Kelvin (4-wire) sense points** on the core rail as close to the die's power balls as practically accessible, separate from the VRM's own remote-sense connection, so bench measurement of actual die-side voltage (not just VRM output voltage) is possible during bring-up and debug.
- Current can be measured indirectly via the VRM controller's built-in current telemetry (read over PMBus) or, for independent verification, via a calibrated shunt or current-sense transformer inserted in early bring-up prototypes — full accelerator-class boards often include on-board current-sense amplifiers on each phase or on the combined output specifically for this purpose, reported to the BMC.
- Thermal instrumentation (on-die thermal diode/sensor read via the SoC's own interface, plus board-mounted thermistors near the VRM power stages and inductors) feeds both the fault-shutdown logic and general thermal characterization during bring-up.

## What's realistically learnable at hobby-fab scale

You will not build a data-center-class accelerator board at JLCPCB/PCBWay prototype pricing — the layer count (12–26+), HDI microvia requirements, exotic laminates, and connector/die packages involved require specialized fabs, assembly houses, and typically NDA'd component access. However, the underlying principles are directly practicable at small scale:

- **Multiphase VRM design**: buildable and testable with commercially available multiphase controller + smart power stage ICs (many vendors sell accessible parts down to a few amps per phase, 2–6 phase) driving a lower-power FPGA/SoC core rail — same architecture, smaller scale.
- **Dense via-stitched power planes**: practicable on a 6–10 layer hobby-fab board for a moderate-current (tens of amps) rail — same IR-drop reasoning applies at smaller numbers.
- **BGA escape/fanout technique**: directly practicable down to 0.5 mm pitch on standard prototype fabs, and down to 0.4 mm with an HDI-tier order from JLCPCB/PCBWay-class fabs.
- **Power sequencing and PMBus telemetry**: fully practicable with off-the-shelf sequencer/PMBus controller ICs on any small board.
- **Thermal/mechanical stiffener design**: practicable conceptually and at small scale (e.g., a stiffener frame around a BGA under a heatsink) even if the specific loads are far smaller than a data-center accelerator card.

Treat a GPU/accelerator-class board primarily as an architecture-literacy topic: understand why it's built the way it is, and practice each sub-technique at a scale your fab and budget can actually deliver.

## Quick reference: pitch vs escape strategy

| BGA pitch | Via/fanout strategy | Typical layer count | Fab tier needed |
|---|---|---|---|
| 1.0 mm | Dog-bone, through-hole via | 1–2 | Any standard fab |
| 0.8 mm | Dog-bone, through-hole via | 2–4 | Standard fab |
| 0.65 mm | Dog-bone outer rows, blind via inner | 4–6 | Standard, HDI helps |
| 0.5 mm | Microvia, via-in-pad common | 6–10 | HDI tier |
| 0.4 mm | Any-layer HDI, via-in-pad mandatory | 10–20+ | Specialized/HDI fab |

## Quick reference: multiphase VRM scaling

| Rail current class | Typical phase count | Power stage type | Controller interface |
|---|---|---|---|
| < 20 A | 1–2 phases | Integrated FET/driver | I2C/PMBus optional |
| 20–60 A | 3–6 phases | Smart power stage | PMBus common |
| 60–150 A | 6–12 phases | Smart power stage | PMBus standard |
| 150–400+ A | 12–20+ phases | Smart power stage, current sharing | PMBus + BMC telemetry |

## Worked example: estimating layer count for a 0.5 mm, 676-ball BGA

Assume a 26×26 ball grid at 0.5 mm pitch (a common mid-size FPGA/SoC footprint). The outer 1–2 rows can dog-bone escape on the top routing layer. Every interior ring beyond that needs its own via/routing layer to reach the surface without colliding with outer-row structures. For a 26-ball-per-side array, roughly 10–12 interior rings remain after removing the outer 2 rows — in practice, HDI stacked/staggered microvias let multiple rings share fewer physical routing layers than a 1:1 ring-to-layer mapping would suggest, which is why real designs at this ball count commonly land in the 8–12 signal-layer range (plus dedicated plane layers) rather than 10+ dedicated escape layers alone. This estimate is a starting point for a stackup discussion, not a substitute for an actual fanout study in the PCB tool.

## Typical multiphase VRM circuit (in words)

An input DC bus (commonly 12V) feeds the input capacitor bank and the high-side connection of each phase's smart power stage. The multiphase PWM controller generates one interleaved PWM output per phase, each routed to the corresponding smart power stage's PWM input pin. Each smart power stage's switch-node output connects to one terminal of that phase's output inductor; the inductors' other terminals all tie together at a common output rail node, which also connects to the output capacitor bank (a mix of bulk and ceramic capacitors) and ultimately to the load (the die's core power balls, through the power plane/via array). Each smart power stage reports current and temperature telemetry back to the controller over a dedicated analog or digital telemetry pin. The controller communicates with the board management controller over PMBus (SDA/SCL plus an address-select network), receiving voltage-setpoint commands and reporting rail status/telemetry. A remote voltage-sense pair (separate small-signal traces, not carrying load current) runs from the controller's sense inputs directly to the load point (near the die's power/ground balls) to compensate for IR drop in the power delivery path.

## Typical power-plane via-stitching pattern (in words)

Directly beneath the accelerator die's power and ground balls, a dense grid of vias connects the relevant BGA pads through every parallel plane layer assigned to that rail — each power via lands on every power-plane layer for that rail, and each ground via lands on every ground-plane layer, with power and ground vias interleaved at close, regular spacing across the whole area under the die's power/ground ball field, not just at the field's perimeter. This dense interleaving keeps both the DC resistance (spreading current across many parallel via/plane paths) and the loop inductance (keeping power and return current paths physically close together) low across the entire power delivery path from VRM to die.

## Common mistakes

- Treating via-in-pad as optional at fine pitch and hitting reflow voiding because the via wasn't filled/capped.
- Underestimating layer count needed for a high ball-count, fine-pitch BGA and discovering mid-layout that routing can't be completed.
- Sizing a single-phase regulator for a rail that actually needs multiphase because of transient current steps, leading to voltage droop the die's brownout/reset circuitry trips on.
- Ignoring IR drop across power planes on high-current rails and finding the die undervoltage at full load despite the regulator's output being correct at its own sense point (regulator remote-sense placement matters — sense at the load, not at the regulator output pad, for tight-tolerance rails).
- Assuming HBM or other in-package memory needs board-level routing/decoupling attention it doesn't — effort belongs on the package's external interfaces instead.
- Skipping power sequencing validation and letting a die see rails in the wrong order during first power-up.

## Schematic review checklist

- BGA ball map cross-checked against datasheet (pitch, ball count, power/ground vs signal ball locations) before layer count is committed.
- Multiphase controller's phase count and current-per-phase rating checked against the rail's worst-case transient and steady-state current, with margin.
- PMBus/telemetry connections from VRM controller to BMC/sequencer shown explicitly, including address-strap resistors if required.
- Power sequencing requirements from the die vendor's datasheet captured as an explicit sequence/timing note, with the sequencing implementation (dedicated IC, PMBus-programmed, or supervisory logic) shown.
- Remote voltage sense (if used) routed as a separate low-current Kelvin-sense connection to the load, not tied to the power delivery trace.

## Layout review checklist

- Escape routing plan for the BGA matches the pitch-based guidance above; via-in-pad fill/cap specified in fab notes where used.
- Power plane layer count and copper weight for the core rail justified by an IR-drop calculation or simulation, not assumed adequate.
- Dense via stitching present under/around high-current BGA power balls, with adjacent ground return vias at similar density.
- VRM phases and their power stages placed symmetrically around the load with short, low-inductance connections to their inductors and output capacitance; output caps distributed near the die's power pins, not clustered only at the VRM.
- Stiffener/backplate mechanical footprint and mounting holes accounted for if the design includes a heatsink/cold-plate with significant clamping force.
- No attempt made to "route HBM" or any in-package memory interface — confirm those balls simply don't exist on the external BGA footprint.
- Bring-up test points present on every independently sequenced rail for bench verification before full power-up.
