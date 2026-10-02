---
title: Stackup and Layer Count Selection
domain: fabrication
tags: [stackup, layer-count, HDI, microvia, dielectric, impedance, copper-weight, prepreg]
applies_to: [digital, high-speed, BGA, GPU/accelerator, general PCB]
---

## Why layer count is decided early

Layer count sets cost, routing density, EMI performance, and impedance control before a single trace is drawn. Changing it mid-project usually forces a re-layout. Decide it from three inputs: (1) the tightest BGA pitch and ball count on the board, (2) the number of independent high-speed interfaces (DDR, PCIe, USB3, Ethernet, HDMI/MIPI), and (3) power rail count and current.

## Choosing layer count by BGA escape

A device's pitch determines whether you can escape signals on outer layers alone or need buried layers and vias-in-pad.

- **≥0.8 mm pitch, ≤200 balls** (most MCUs/FPGAs entry-level, power ICs): 2–4 layers usually escape fine with standard vias between pads.
- **0.65–0.8 mm pitch, 200–500 balls** (mid FPGAs, SoCs): 4–6 layers; dog-bone fanout on layer 1, route-outs on layers 2–3, may need blind vias for the inner ball rows.
- **0.5 mm pitch, 400–1000+ balls** (application processors, mid FPGAs, DDR4 SoCs): 6–10 layers, HDI with microvias (laser-drilled, ≤0.15 mm) needed to reach inner rows; via-in-pad with filled/plated vias is common.
- **0.4 mm pitch or less, 1000+ balls** (mobile SoCs, high-end FPGAs, GPU/accelerator packages): any-layer HDI, 10–20+ layers, stacked microvias, via-in-pad mandatory. This is beyond hobby-fab capability; see `bga_fanout_and_gpu_class_boards.md`.

Rule of thumb for the number of signal-escape layers needed under a fine-pitch BGA: every additional row of balls beyond what one layer can dog-bone-escape roughly needs one more routing layer, because only the outermost 1–2 rows can fan out on the surface layer before you run out of space between pads.

## Canonical stackups

Copper weights below assume 1 oz (35 µm) outer, 0.5–1 oz inner unless noted; adjust for high current.

### 2-layer
- L1: Signal/Component (top)
- L2: Signal/Component (bottom)
- Use: simple boards, no controlled impedance guarantees without careful trace width calc against the single dielectric (typically 1.6 mm FR-4 core). No real plane, so return current path is whatever trace/copper pour is nearest — expect poor EMI performance above a few tens of MHz.

### 4-layer (most common minimum for anything with a MCU + USB/Ethernet)
- L1: Signal (component side, some routing)
- L2: GND plane
- L3: Power plane (or GND + power split by rail)
- L4: Signal (routing + component side)

This gives one continuous reference plane adjacent to each signal layer — the workhorse stackup for digital boards up to ~100 MHz clocks and moderate USB/Ethernet.

### 6-layer
- L1: Signal (high-speed routing, controlled impedance)
- L2: GND (reference for L1)
- L3: Signal (inner routing)
- L4: Power plane(s)
- L5: GND (reference for L6)
- L6: Signal (component side, routing)

Alternative "signal-plane-signal-plane-signal-signal" arrangements exist; the key principle is **every signal layer has an adjacent, unbroken reference plane** (GND preferred, power acceptable if solid).

### 8-layer (DDR3/DDR4, PCIe Gen3, multi-rail boards)
- L1: Signal (top, high-speed)
- L2: GND
- L3: Signal (stripline, e.g. DDR data/addr)
- L4: Power (split planes per rail as needed)
- L5: GND
- L6: Signal (stripline)
- L7: GND (or power, whichever balances the stack)
- L8: Signal (bottom)

Gives two stripline signal layers tightly sandwiched between ground for the noisiest nets (DDR, PCIe), plus two microstrip layers on top/bottom for lower-speed I/O.

### 10-layer (dense SoC + DDR4 + PCIe + Ethernet)
Typical order: Sig–GND–Sig–PWR–GND–Sig–PWR–GND–Sig–Sig or similar, always keeping signal layers plane-adjacent and putting DDR/PCIe on inner stripline pairs closest to the die/BGA to minimize via transitions.

### 12–16 layer (accelerator carrier boards, complex SoCs, multi-DDR-channel)
Typically 4–6 signal layers dedicated to high-speed stripline pairs, 2–4 dedicated power layers (split by rail: core, DDR VDD, I/O, aux), remaining GND layers interleaved so no two signal layers are ever adjacent without a plane between them. HDI (see below) is standard at this density.

### 16+ layer, GPU/accelerator class
See `bga_fanout_and_gpu_class_boards.md` for the specifics of high-current core-rail power distribution, but structurally these use HDI build-ups (multiple microvia sequences) around a thicker core, often 18–26+ layers total, with dedicated plane pairs for each major voltage rail and multiple ground layers for isolation between analog/RF, digital, and power sections.

## Symmetry, warp, and mechanical stability

- Stackups should be **symmetric about the center** (copper weight and dielectric thickness mirrored top-to-bottom). Asymmetric stackups warp during reflow because the copper/resin CTE mismatch pulls unevenly — IPC-6012 does not mandate symmetry directly, but fabricators will flag and often reject asymmetric builds for reliability.
- Keep copper balance similar per layer (avoid one layer being 80% copper pour next to one that's 10%) to reduce differential shrinkage during lamination.
- A standard 1.6 mm (62 mil) finished thickness is the default unless the connector or enclosure dictates otherwise; thinner boards (0.8–1.0 mm) are common for HDI/mobile designs but are more prone to flex damage—consider stiffeners for large connectors.

## Prepreg vs core, dielectric constant

- **Core**: fully cured, copper-clad both sides, dimensionally stable — the "reference" layers are built from these.
- **Prepreg (pre-impregnated glass fabric + resin)**: uncured, used to bond cores together during lamination; it flows and cures under heat/pressure.
- Standard FR-4 Dk (dielectric constant) is roughly 4.2–4.5 at 1 MHz, dropping to ~3.9–4.3 around 1 GHz depending on resin/glass-weave; **Df (loss tangent)** ~0.02, too lossy for multi-Gbps signals over long runs.
- For PCIe Gen4/5, DDR5, 10G+ Ethernet, or long RF traces, use **low-loss laminates** (e.g., Isola 370HR as a "mid" step up from generic FR-4, or Megtron-6/7, Rogers 4350B for very low loss / RF) with Df down to 0.003–0.01 and tighter Dk tolerance.
- Glass weave style (1080, 2116, 7628, etc.) affects both Dk uniformity (fiber-weave effect / glass-weave skew) and achievable minimum dielectric thickness; specify weave for tight length-matched differential pairs.

## Copper weight selection

- 0.5 oz (17.5 µm) inner layers: fine-pitch routing, low current signal layers.
- 1 oz (35 µm): standard default, both outer and inner.
- 2 oz (70 µm) or heavier: power planes carrying multiple amps, motor drivers, high-current rails — but heavier copper increases minimum trace/space (etch factor) and cost. Many fabs require wider minimum spacing (often stepping from ~4 mil to ~6–8 mil min space) as copper weight increases beyond 1 oz.
- For planes carrying tens to hundreds of amps (GPU core rails), use 2–4 oz planes with paralleled layers and heavy via stitching rather than relying on a single very thick layer.

## HDI: microvias, stacked/staggered, any-layer

- **Microvia**: laser-drilled, typically ≤0.15 mm (6 mil) finished hole diameter, connects only one layer pair (usually surface to first inner layer), aspect ratio ~0.8:1–1:1.
- **Blind via**: connects an outer layer to an inner layer without going through the whole board.
- **Buried via**: connects two inner layers only, invisible from either surface.
- **Stacked microvias**: microvias directly on top of each other through multiple layer pairs — highest density, highest cost, needs via fill/plate-over to support stacking reliably.
- **Staggered microvias**: offset from each other, each landing on its own pad — cheaper and more reliable than stacked, needs more area.
- **Any-layer HDI**: every layer pair can carry a microvia, enabling escape from very fine pitch BGAs (0.4 mm and below) in minimal layer count; standard at high-volume mobile/SoC fabs, but a premium (and often minimum-order-quantity-gated) service at general-purpose fabs.
- **Via-in-pad**: via placed directly inside an SMD/BGA pad instead of pulled out with a dog-bone. Required at fine pitch. Must be **filled and capped/plated over** (IPC-4761 Type VII typically) so solder paste doesn't wick into the hole during reflow — an unfilled via-in-pad on a critical pad is a classic manufacturing defect leading to voiding/insufficient solder.

## Setting up the stackup in KiCad

1. **Board Setup → Physical Stackup**: set layer count first (Board Setup → Board Editor Layers → enable the layers you need), then go to Physical Stackup to define per-layer material, thickness, and Dk/Df.
2. Use "Add Dielectric Layer" for each prepreg/core; KiCad auto-computes total board thickness — verify it lands near your target (e.g., 1.6 mm) and adjust core/prepreg thickness to match a fab's standard offerings (don't invent a stackup a fab can't build — check the fab's stock stackup table for your layer count first).
3. Assign net classes and use the **impedance calculator dialog** (Physical Stackup panel has an "Impedance Calculator" tab in recent KiCad, or use an external tool like Saturn PCB Toolkit) to size trace widths against the dielectric you defined — do this stackup step *before* routing controlled-impedance nets, since trace width targets depend on layer position and dielectric thickness.
4. For HDI, KiCad supports differing via **span** definitions per net class/rule (blind/buried vias configured per padstack or via) since KiCad 7+; assign microvia vs standard via per net where the routing plan requires it.
5. Keep a written stackup table (layer name, material, thickness, Dk) in the fab notes / plot output so the fabricator builds exactly what you simulated.

## Fab capability tiers

- **JLCPCB/PCBWay-class (standard, high-volume prototype fabs)**: reliably offer 1–8 layers standard, 10–14 on request; HDI (1-2 sequential laser microvia builds) available as a specific service tier; min trace/space commonly 3.5–4 mil (0.09–0.1 mm) on standard service, tighter (down to ~2–3 mil) on advanced/HDI tiers; min via drill ~0.15 mm mechanical, ~0.1 mm laser microvia; typical turn times days, not weeks. Good for learning, prototypes, and boards up to moderately dense BGAs (0.5 mm pitch is generally fine; 0.4 mm is borderline and needs explicit HDI order).
- **High-end/aerospace-grade fabs**: any-layer HDI, 20+ layers, exotic laminates (Rogers, Megtron), controlled-impedance certification with test coupons, IPC Class 3 build and inspection, blind/buried via stacks 3+ deep, longer lead times (weeks) and NRE (non-recurring engineering) costs, often require minimum order quantities incompatible with single-prototype hobby budgets.
- Always confirm a fab's **capability table** (min trace/space, min drill, max layer count, aspect ratio, available laminates) before finalizing stackup — do not assume advanced options are available without checking.

## Impedance calculation fundamentals

- Microstrip characteristic impedance depends primarily on trace width, dielectric thickness to the reference plane, dielectric constant (Dk), and copper thickness — widening a trace lowers impedance, moving the reference plane further away (thicker dielectric) raises it, and higher Dk lowers it. Stripline impedance follows similar relationships but references the distance to two planes (above and below) rather than one.
- Use a field-solver-based calculator (KiCad's built-in impedance calculator tool, or standalone tools like Saturn PCB Toolkit or a fab-provided calculator) rather than a simple closed-form formula for final trace-width decisions — closed-form approximations (e.g., simplified microstrip equations) can be off by enough to matter for tight-tolerance designs, especially near dielectric edges or with non-standard copper weights.
- Always recompute impedance targets whenever the stackup changes (different core/prepreg thickness, different Dk laminate, different copper weight) — a trace width that hit 50 Ω on one stackup revision will not automatically still be correct after a stackup change, even a seemingly minor one like switching prepreg thickness by a few mil.

## Stackup documentation for the fab

- Provide the fab with an explicit, unambiguous stackup table: layer name/number, material type (core vs prepreg), nominal thickness, Dk/Df where relevant, and target copper weight per layer — do not rely on the fab to infer your intended stackup purely from a generic "N-layer" order without this detail, since fabs maintain multiple different stock stackups per layer count and will default to their standard unless told otherwise.
- Where controlled impedance matters, state the calculated trace width/spacing alongside the target impedance and note that the fab should confirm (or adjust construction slightly, common practice) to hit the target — many fabs will fine-tune actual dielectric thickness within a small tolerance band to hit your stated impedance target more precisely than a purely nominal stackup would, but only if you tell them the target explicitly rather than just handing over Gerbers.

## Choosing between JLCPCB/PCBWay-class and a specialized fab: a practical decision framework

- Use a standard prototype fab (JLCPCB/PCBWay-class) when: layer count is ≤10 (or ≤14 on their extended service), BGA pitch is ≥0.5 mm (or 0.4 mm if their HDI tier is explicitly ordered), the application does not require IPC Class 3 build/inspection, and turnaround/cost matter more than exotic laminate performance.
- Move to a specialized/high-end fab when: layer count exceeds what the standard fab publishes in its capability table, any-layer HDI or 3+ deep stacked microvias are required, exotic laminates (Rogers, Megtron-6/7) are needed for RF or very high-speed performance, IPC Class 3 build and documented process control/inspection records are contractually required, or the application needs qualification testing (thermal cycling, vibration) that a hobby-tier fab doesn't offer as a service.
- A middle ground exists: several of the same prototype-fab-class companies (JLCPCB/PCBWay and similar) offer a distinct "advanced" or "HDI" service tier that closes much of the capability gap (any-layer HDI, tighter trace/space, more layer options) at a price and lead-time premium over their standard tier but still well below a specialized fab's cost/MOQ — worth checking before assuming a design needs to jump straight to a specialized fab.

## Quick reference: layer count by application

| Layer count | Typical application | Notes |
|---|---|---|
| 2 | Simple, low-speed, low-cost boards | No true reference plane |
| 4 | MCU + USB/Ethernet, general digital | Workhorse stackup |
| 6 | Moderate density, some high-speed | First tier with stripline option |
| 8 | DDR3/DDR4, PCIe Gen3, multi-rail | Common SoC carrier board tier |
| 10 | Dense SoC + DDR4 + PCIe + Ethernet | HDI often starts here |
| 12–16 | Accelerator carrier, complex SoC | HDI standard |
| 16+ | GPU/accelerator-class | HDI mandatory, specialized fab |

## Quick reference: dielectric properties (approximate, verify with laminate datasheet)

| Laminate class | Dk (~1–10 GHz) | Df (loss tangent) | Typical use |
|---|---|---|---|
| Generic FR-4 | 3.9–4.5 | ~0.02 | General digital, <5 Gbps |
| Mid-loss (e.g., Isola 370HR class) | ~3.9–4.1 | ~0.01 | PCIe Gen3, moderate speed |
| Low-loss (e.g., Megtron-6 class) | ~3.4–3.7 | ~0.003–0.005 | PCIe Gen4/5, 10G+ Ethernet |
| RF laminate (e.g., Rogers 4350B) | ~3.48 | ~0.0037 | RF/microwave, antennas |

## Quick reference: copper weight selection

| Copper weight | Thickness | Typical use |
|---|---|---|
| 0.5 oz | 17.5 µm | Fine-pitch inner routing layers |
| 1 oz | 35 µm | Standard default, outer and inner |
| 2 oz | 70 µm | Power planes, several-amp rails |
| 3–4 oz | 105–140 µm | High-current power distribution |

## Typical 8-layer stackup build (in words)

From top to bottom: a 1 oz outer copper signal layer (L1, microstrip, high-speed routing and component placement) bonds via prepreg to an inner 0.5–1 oz ground plane (L2), which bonds via a core to another inner signal layer (L3, stripline, used for the noisiest nets such as DDR data/address since it sits fully between two planes), which bonds via prepreg to a power plane (L4, potentially split into multiple isolated pours for different rails), which bonds via a core to a second ground plane (L5), which bonds via prepreg to a second stripline signal layer (L6), which bonds via a core to a third plane layer (L7, ground or power depending on which balances the stack's copper distribution and rail needs), which finally bonds via prepreg to the bottom outer copper signal layer (L8, microstrip, component placement and lower-speed routing). Total copper and dielectric distribution is kept symmetric top-to-bottom around the board's center to avoid warp, and every signal layer (L1, L3, L6, L8) has at least one immediately adjacent, unbroken reference plane.

## Ordering a stackup from a fab: what to send

- A written stackup table listing every layer's material (core/prepreg), nominal thickness, copper weight, and Dk/Df where relevant.
- The target impedance and calculated trace width/spacing for every controlled-impedance net class, so the fab can fine-tune actual construction if needed.
- The overall target finished board thickness.
- Any HDI/microvia requirements (span, stacked vs staggered, via-in-pad fill/cap) called out explicitly, not left implicit in the Gerber files.
- A request for impedance test coupons if the design has tight-tolerance controlled-impedance requirements.

## Common mistakes

- Routing high-speed signals on a layer with no adjacent reference plane (e.g., between two signal layers) — causes uncontrolled impedance and large return-current loops.
- Splitting the ground plane under a high-speed trace's route (a slot in the plane the trace crosses) — forces return current to detour, radiating EMI and adding inductance.
- Asymmetric stackup causing warp that fails reflow or connector seating.
- Assuming your fab can do any-layer HDI with only a datasheet's typical capability list — always confirm on their actual capability doc for your specific job.
- Using generic FR-4 for a design with PCIe Gen4+/DDR5/10G Ethernet and being surprised by eye-diagram failures from excessive dielectric loss.
- Not filling via-in-pad on fine-pitch BGA, leading to solder voiding.

## Schematic review checklist

- Every IC's power pins are grouped and every decoupling cap is explicitly shown near its associated power pin net, not just implied.
- Voltage rails needed (core, I/O, aux, analog) are all enumerated and match what the chosen stackup's power layers can deliver.
- BGA pin/ball count and pitch are confirmed from the datasheet before layer count is finalized.
- High-speed interfaces (count them: DDR channels, PCIe lanes/x-count, USB3 ports, Ethernet PHYs) are tallied so routing-layer budget can be sized.
- No net requiring controlled impedance is left without a note on target impedance (50 Ω SE, 90 Ω USB, 100 Ω diff, etc.).

## Layout review checklist

- Stackup defined in KiCad Board Setup matches an actual fab-supported stackup (checked against the fab's capability table), not an idealized one.
- Every signal layer has an unbroken adjacent reference plane; note any exceptions and why they're acceptable (e.g., low-speed layer).
- Symmetric copper/dielectric distribution top-to-bottom confirmed.
- Copper weight adequate for planned current on each power plane (use IPC-2221B trace-current tables or a calculator, not guesses).
- Via type (through, blind, buried, microvia) matches what was actually ordered/available from the fab, with aspect ratios within the fab's stated capability.
- Via-in-pad locations are flagged for fill+cap in fab notes if used.
- Stackup table exported and included in fab package (drill table, layer stack drawing) so the fabricator cannot ambiguously reinterpret it.
