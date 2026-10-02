---
title: DFM/DFA — Fabrication and Assembly Design Rules
domain: fabrication
tags: [DFM, DFA, panelization, fiducials, test-points, solder-mask, tented-vias, silkscreen, Gerber, ODB++, IPC-2581, JLCPCB, DRC]
applies_to: [general PCB, fabrication, assembly]
---

## Core design rules (standard prototype-fab tier, e.g., JLCPCB/PCBWay standard service)

Values below are typical for standard-tier 1–8 layer prototype fabrication as of general industry practice; always confirm against your chosen fab's current capability table before finalizing, since these tiers are periodically updated and vary between "standard," "advanced/HDI," and premium services.

- **Minimum trace width/spacing**: commonly 3.5–4 mil (0.09–0.1 mm) on standard service, down to 2–3.5 mil on advanced/HDI service. IPC-2221B provides general conductor spacing tables based on voltage between conductors and altitude (coated/uncoated) — use it for high-voltage nets (e.g., mains, HV supply sections) rather than assuming the fab's minimum is electrically safe at your operating voltage.
- **Minimum annular ring**: commonly 4–5 mil (0.1–0.13 mm) minimum for standard through-hole vias at standard tier; IPC-6012 Class 2 default vs Class 3 tighter/more conservative acceptance criteria (see `aerospace_defense_and_high_reliability.md`).
- **Minimum drill size**: commonly 0.2–0.3 mm (mechanical drill) on standard tier, down to ~0.1 mm for laser-drilled microvias on HDI tier.
- **Minimum via diameter (pad)**: commonly around 0.45–0.6 mm typical pad for a 0.3 mm drill on standard tier — always let the fab's capability table or a via-size calculator (rather than a fixed guess) set this, since fab-to-fab variation exists.
- **Board outline tolerance, min board size/thickness**: standard tier typically supports 0.4–3.2 mm finished thickness, with panelization needed below a certain minimum single-board size (commonly under roughly 50×50 mm, fab-dependent) since very small boards are impractical to run singly through the assembly line.

## Panelization

- Multiple copies of a board (or multiple different boards) are arranged into a **panel** for efficient fab/assembly processing — either a fab-side panel (the fabricator panelizes your single board design automatically for their own process, common at prototype quantities) or a **designer-supplied panel** (you provide the panel array yourself, common when you need specific panel dimensions for your own pick-and-place/reflow process, or when ordering assembly).
- **V-scoring**: a V-shaped groove cut partway through the board thickness along the panel's break lines, allowing boards to be snapped apart after assembly — works well for straight-line breaks but requires adequate keep-out (commonly a few mm) from components near the V-score line since the snapping process induces mechanical stress.
- **Tab-routing (mouse bites)**: the panel outline is routed (milled) around each board's perimeter except for small unrouted tabs (perforated with small drill holes, "mouse bites") holding boards together; boards are broken apart post-assembly by hand or with a depanelizer. Allows non-rectangular/non-straight board outlines that V-scoring can't achieve, but leaves small nub remnants on the board edge after breaking (must be accounted for if edge finish matters).
- Include panel-level **fiducials** (see below) and rails with adequate width (commonly 5–10 mm) for the assembly line's conveyor/edge-clamping if supplying your own panel.

## Fiducials

- **Global fiducials**: typically 2–3 per panel/board (a minimum of 2 defines rotation+offset; 3 improves accuracy and lets the pick-and-place machine correct for any panel skew), placed at diagonal corners, used by the pick-and-place machine's vision system to precisely register the board's actual position/rotation versus the nominal CAD position before placing parts.
- **Local (per-component) fiducials**: additional smaller fiducials next to very fine-pitch parts (e.g., BGAs, QFN, fine-pitch QFP) to correct for any local placement drift beyond what global fiducials capture, recommended for pitch ≤0.5 mm parts on tight-tolerance assembly.
- Fiducial standard: a round copper pad (commonly 1 mm diameter) with a clear soldermask opening at least the pad diameter plus margin (commonly 2–3 mm clearance to any other copper/silkscreen) so the vision system sees an unambiguous, high-contrast circular target — do not cover a fiducial with soldermask, silkscreen, or place it near other copper features that could confuse the vision algorithm.

## Test points (ICT / flying probe)

- **In-circuit test (ICT)** uses a fixed bed-of-nails fixture contacting dedicated test points to verify component presence/value/connectivity at high speed — economical only at higher production volumes given the fixture's NRE cost.
- **Flying probe test** uses movable probes (no fixed fixture) to contact test points or component leads directly — better suited to prototype/low-volume runs since it needs no dedicated fixture, but is slower per-board.
- Provide accessible test points (via, dedicated pad, or component lead) for every net that's practical to test, sized adequately for the chosen test method (flying probe can often use a smaller pad than ICT's bed-of-nails, which needs a minimum pad size, commonly around 1 mm² or larger per test point, fixture-dependent) and located with adequate spacing from tall components so a probe/nail can physically land without obstruction.
- For boards with no dedicated test points at all, testing (and outsourced assembly review) becomes significantly harder — at minimum, expose test points on power rails and any signal the design would need to debug/verify in production.

## Solder mask and paste

- **Solder mask** (typically green by default, other colors available at most fabs at similar or modest extra cost) covers copper not intended to be soldered, preventing solder bridging between adjacent pads and protecting traces from oxidation/short circuits.
- **Solder mask expansion/swell**: solder mask openings are typically slightly larger than the copper pad (commonly ~2–3 mil expansion per side) to accommodate registration tolerance between the mask layer and copper layer during fabrication — check whether your design uses mask-defined pads (mask opening smaller than pad, common for BGA to precisely define the solderable area) vs. copper-defined/non-mask-defined pads (mask opening larger than pad, the more common default for general SMD) and confirm the fab's default matches your intent.
- **Solder paste stencil**: a laser-cut (or electroformed for very fine pitch) stainless steel stencil defines where paste is deposited before reflow; stencil thickness (commonly 0.1–0.15 mm/4–6 mil standard) is chosen as a tradeoff between adequate paste volume for larger/standard components and avoiding solder bridging/excess paste on fine-pitch parts — a **step stencil** (varying thickness across the stencil, thinner over fine-pitch areas) is used when a single board has both standard and very fine-pitch parts needing different optimal paste volumes.

## Component spacing

- Maintain adequate spacing between adjacent component courtyards (IPC-7351 defines standard footprint courtyard requirements per package type/density level — Level A "Maximum" for hand assembly/rework friendliness, Level B "Nominal" default for standard SMT assembly, Level C "Least" for highest density where hand rework is not expected) so the pick-and-place machine's nozzle and any post-reflow rework tooling can physically access each part without disturbing neighbors.
- Leave adequate clearance around connectors, especially through-hole/mixed-technology connectors requiring wave or selective soldering, since these often need larger keep-out for the soldering process/fixture.
- Keep tall components away from panel V-score/tab lines and from the edges of any board section that will be flexed/handled during depanelization.

## Thermal relief

- Through-hole pads and vias connecting to a large copper pour/plane should use a **thermal relief** pattern (spokes connecting the pad to the plane rather than a solid direct connection) so hand or wave soldering heat isn't rapidly sunk away by the large copper mass, which can cause cold/incomplete solder joints on through-hole parts.
- SMD pads generally should connect to planes with a more direct (fewer/no thermal relief spokes) or short, low-inductance connection instead, since reflow doesn't have the same heat-sinking problem as hand/wave soldering, and a solid connection reduces impedance for high-current or high-speed SMD pads — the design-rule default in most PCB tools (including KiCad's zone properties) lets you set thermal relief spoke count/width per pad or globally per net class; don't leave every pad on thermal-relief spokes by default without considering whether it's actually the right choice per pad type.

## Tented vias

- **Tenting**: covering a via with solder mask (fully "tented," partially covering, or left fully open/"untented") to prevent solder wicking into the via barrel during reflow/wave soldering and to protect against contamination/oxidation.
- Fully tented vias are standard default for vias not intentionally used as test points or thermal/via-in-pad structures; specify tenting explicitly in fab notes if your CAD tool's default doesn't match what you want (some vias may need to stay open, e.g., if used deliberately as a test point or for via-in-pad fill/cap processing, which is a different, explicit fab process — see `bga_fanout_and_gpu_class_boards.md`).
- Tenting is not the same as via-in-pad filling — tenting is a mask-covering step on a regular via; via-in-pad fill/cap is a dedicated epoxy-fill-and-plate-over process for vias inside SMD/BGA pads.

## Silkscreen

- Minimum silkscreen line width and text height are fab-dependent (commonly a minimum ~4–5 mil line width, ~0.8–1 mm text height for legibility) — text smaller than the fab's minimum may not print legibly or at all.
- Do not place silkscreen text or graphics over exposed copper pads (solder mask should separate silkscreen from any pad it might overlap) — silkscreen ink on a pad interferes with solder wetting and is a classic novice-design mistake caught in DFM review.
- Include reference designators for every component (readable, not overlapping component bodies or other text after placement — verify with a final silkscreen-vs-placement visual pass), polarity marks for polarized parts (diodes, electrolytic caps, connector pin-1 indicators), and board identification (name, revision, date) in a consistent location.

## BOM and CPL for turnkey assembly (e.g., JLCPCB assembly service)

- **BOM (Bill of Materials)**: a spreadsheet/CSV listing every component with reference designator(s), value, footprint, and — critically for turnkey assembly — the manufacturer part number (MPN) and, where the assembler uses their own parts catalog (e.g., JLCPCB's "Basic" vs "Extended" parts library), the matching catalog part number, since assembly houses match your BOM against their in-stock library for basic-part discounts and to avoid substitution ambiguity.
- **CPL (Component Placement List, also called "Pick and Place" or "PnP" file)**: lists each component's reference designator, X/Y position, rotation, and layer (top/bottom) — generated directly from your PCB CAD tool's footprint placement, used to program the pick-and-place machine.
- Common failure points: reference designator mismatches between BOM and CPL/schematic, rotation convention mismatches (many assembly houses expect IPC-7351-standard part rotation; a part placed correctly by your CAD tool's own convention can still be backwards per the assembler's expected convention — check the assembler's rotation guide, especially for polarized 2-pin parts like diodes/tantalum caps, and connectors/asymmetric packages), and missing/ambiguous MPN leading to a wrong-part substitution.
- Always generate BOM/CPL directly from the finalized PCB design (via the export tool, not hand-typed) to avoid transcription drift between schematic, layout, and the files sent to assembly.

## Gerber, ODB++, and IPC-2581 outputs

- **Gerber (RS-274X)**: the traditional layer-by-layer vector image format (one file per copper layer, solder mask, silkscreen, etc.) plus a separate drill file (Excellon format) — universally supported by every fab, but is a collection of loosely-related files with no single authoritative net/stackup/drill-pairing definition, leaving room for misinterpretation (which is why a clear stackup drawing and drill table should always accompany a Gerber package).
- **ODB++**: a single unified job file format bundling all layers, drill data, netlist, BOM, and stackup information together, reducing ambiguity versus a loose Gerber set — widely supported by modern fabs and preferred by many for its completeness.
- **IPC-2581**: an open XML-based standard (IPC's own format, intended as a vendor-neutral alternative/successor direction to ODB++) bundling the same categories of information (layers, drill, netlist, BOM, stackup) in a standardized schema — increasingly supported by fabs and EDA tools, worth using where supported since it's an open published standard rather than a single-vendor format.
- In KiCad, generate Gerbers/drill via **File → Fabrication Outputs → Gerbers** (or the Plot dialog) and **Generate Drill Files**; KiCad 8+ also supports direct **ODB++** and **IPC-2581** export from the same fabrication-outputs workflow — prefer ODB++ or IPC-2581 when the target fab explicitly supports it, since it reduces the chance of a misassembled Gerber layer stack, but always cross-check the fab's preferred format before choosing.

## DRC setup in KiCad

- Configure **Board Setup → Design Rules → Constraints** with your target fab's actual minimum trace/space, via size/drill, and annular ring values (do not leave KiCad's generic defaults if your fab's capability differs) before running DRC, since DRC only catches what its configured constraints say to check.
- Set up **net classes** (or custom `.kicad_dru` rules for more complex per-net requirements) matching each interface's controlled-impedance and clearance needs (see `high_speed_signal_integrity.md` and `kicad_workflow_and_best_practices.md` for `.kicad_dru` syntax).
- Run **DRC** (Inspect → Design Rules Checker) after routing is complete and before generating fabrication outputs — treat every unresolved violation as something to either fix or explicitly, deliberately exclude (KiCad supports marking a violation as an "exclusion" with a note) rather than silently ignoring the report.
- Also run the **Electrical Rules Checker (ERC)** at the schematic stage (see `kicad_workflow_and_best_practices.md`) — DRC catches physical/manufacturing rule violations, ERC catches logical/connectivity issues; both are needed before release.

## Reflow profile and thermal considerations at design time

- The board's thermal mass distribution (large copper pours, heavy copper weight, many large components clustered in one area) affects how evenly the assembly heats during reflow — a design with a very large, thick copper ground plane directly under a fine-pitch BGA can act as a heat sink that slows local heating, risking cold joints on that part if the assembler's reflow profile isn't tuned for it; flag unusual thermal-mass concentrations to your assembler, or add thermal relief/reduced-copper zones locally if the design allows it without compromising electrical performance.
- Mixed reflow requirements (e.g., a board needing both standard SAC-alloy lead-free reflow for most parts and a lower-temperature process for a heat-sensitive part) may require a **two-pass reflow** or selective/hand-soldering step for the sensitive part — identify any such component early since it affects assembly process planning and cost, not just the BOM.
- **Lead-free vs leaded process**: most modern commercial assembly defaults to lead-free (RoHS-compliant, SAC-alloy solder, higher reflow peak temperature, commonly around 245–250°C peak) — confirm every component's rated maximum reflow temperature and reflow profile compatibility (check the part's MSL — moisture sensitivity level — rating and recommended reflow profile in its datasheet) against the assembler's standard process before finalizing BOM selections, especially for older or industrial-grade parts that may only be rated for a leaded process.

## Moisture sensitivity level (MSL) and baking

- SMD components (especially plastic-packaged ICs) absorb ambient moisture over time; if a moisture-saturated part is subjected to reflow's high temperature, trapped moisture can flash to steam and crack the package ("popcorning") — each such part carries an **MSL rating** (MSL1 through MSL6, per J-STD-020) defining how long it can be exposed to factory floor humidity conditions after its vacuum-sealed bag is opened before it must be reflowed or re-baked.
- For a design with parts at MSL3 or higher (common for larger BGAs), ensure your assembler's process (or your own, if hand-assembling) accounts for floor-life tracking and bake-out procedures for parts that have exceeded their floor life — this is a real, field-observed failure mode (cracked BGA packages from popcorning) and not merely a theoretical concern once you're using larger plastic BGA packages.

## X-ray inspection for hidden joints

- BGA, QFN (especially with a thermal pad underneath), and other bottom-terminated/hidden-joint packages cannot be visually inspected after reflow — **X-ray inspection** is the standard method for verifying solder joint quality (checking for voids, bridging, or open joints) on these package types.
- Design for X-ray inspectability where practical: avoid stacking components directly on top of each other in the Z-axis in a way that obscures the joint of interest in the X-ray image, and consider whether a design with extensive via-in-pad under a BGA might make void detection harder to interpret (filled vias can appear differently in X-ray than intended solder joint voids, so discuss with your assembler/inspection provider if this is a concern for a critical design).

## Panel-level and coupon testing for controlled impedance

- For designs with controlled-impedance requirements, request the fab include **impedance test coupons** on the production panel — small purpose-built trace structures built in the same process/layer as your actual controlled-impedance traces, measured with a time-domain reflectometer (TDR) by the fab (or a third party) to verify the actual as-built impedance matches your target within tolerance, rather than relying solely on the fab's stackup calculation being accurate for that specific production run.
- This is standard practice for any board where the impedance target has a tight tolerance (e.g., ±7% or better for a demanding SerDes design) and is often available as a standard (sometimes free, sometimes small extra-cost) option even at prototype-tier fabs — always ask if it's not explicitly offered.

## Quick reference: standard-tier prototype fab capability (typical, confirm per fab)

| Parameter | Standard tier | Advanced/HDI tier |
|---|---|---|
| Min trace/space | 3.5–4 mil (0.09–0.1 mm) | 2–3.5 mil |
| Min annular ring | 4–5 mil (0.1–0.13 mm) | Smaller, fab-dependent |
| Min mechanical drill | 0.2–0.3 mm | N/A (laser for microvia) |
| Min laser microvia drill | N/A | ~0.1 mm |
| Max layer count (typical) | 6–8 standard, 10–14 on request | 10–20+ |
| Finished thickness range | 0.4–3.2 mm | Similar, HDI often thinner |
| Fiducial pad diameter | ~1 mm | ~1 mm |
| Impedance tolerance (with coupon) | ±10% typical | ±7–8% achievable |

## Quick reference: IPC standards cited in this guide

| Standard | Scope |
|---|---|
| IPC-2221B | Generic standard for PCB design, conductor spacing/current tables |
| IPC-6012 | Rigid PCB qualification and performance (Class 1/2/3) |
| IPC-A-610 | Acceptability of electronic assemblies |
| IPC-7351 | Land pattern/courtyard standard, density levels A/B/C |
| IPC-4761 | Via protection (tenting, filling, capping) types I–VII |
| J-STD-020 | Moisture sensitivity level classification for SMD packages |

## Quick reference: MSL and floor-life implications

| MSL level | Typical floor life (30°C/60% RH) | Action if exceeded |
|---|---|---|
| MSL1 | Unlimited | None |
| MSL2 | 1 year | Bake before reflow if exceeded |
| MSL3 | 168 hours | Bake before reflow if exceeded |
| MSL4 | 72 hours | Bake before reflow if exceeded |
| MSL5/5A | 24–48 hours | Bake before reflow if exceeded |
| MSL6 | Mandatory bake before use | Must reflow within stated window after bake |

## Typical panel with fiducials and test coupon (in words)

The production panel contains the individual board outlines arranged in a grid (rows and columns) within a surrounding rail border wide enough for the assembly line's conveyor grippers. At two or three diagonal corners of the overall panel (not per individual board, for panel-level fiducials — though fine-pitch boards additionally get their own local fiducials near the sensitive part), a round copper pad with a clear soldermask opening sits isolated from any other copper or silkscreen feature, giving the pick-and-place vision system an unambiguous target. Along one edge of the panel, outside the board outlines but still within the rail area, a small impedance test coupon (a short run of trace built in the same layer/stackup as the design's actual controlled-impedance nets, with an accessible probe pad at each end) lets the fab's quality process measure actual as-built impedance with a TDR before or after the boards are separated from the panel, without consuming usable board area on the product itself.

## Typical ICT/flying-probe test point layout (in words)

Each net selected for test exposes a dedicated small round pad (or, where board space doesn't allow a dedicated pad, an accessible via or component lead) on a single consistent side of the board (commonly the bottom/solder side, kept clear of tall components so a probe can land vertically without obstruction). Power rail test points are placed near the regulator output and, for rails distributed across a large board, additionally near the far end of the distribution to catch IR-drop-related failures the near-side point alone wouldn't reveal. Test points are named in the schematic/BOM with a clear, consistent naming convention (e.g., `TP1`, `TP2` with a net-name cross-reference) so the test house's fixture/probe-program generation tool can map each physical point back to its intended net without ambiguity.

## Common mistakes

- Designing to generic/default DRC values instead of the actual target fab's published capability table, discovering mismatches only after Gerbers are rejected or quoted at higher cost/longer lead time.
- Omitting fiducials, making automated pick-and-place assembly less accurate or impossible for the assembler's standard process.
- Silkscreen text overlapping pads or unreadable after placement (too small, or hidden under a taller neighboring component).
- BOM listing a generic/incomplete part description instead of an exact MPN, risking wrong-part substitution by the assembler.
- CPL rotation not matching the assembler's expected convention for polarized/asymmetric parts, causing components to be placed backwards.
- Leaving through-hole pads solidly connected to large copper pours without thermal relief, causing cold solder joints during hand/wave soldering.
- Forgetting to specify via-in-pad fill/cap explicitly when using via-in-pad, or tenting vias that were meant to be accessible test points.

## Schematic review checklist

- Every component has a manufacturer part number captured (in the symbol's fields) so BOM export needs no manual lookup/guessing later.
- Test-point-worthy nets (power rails, key digital signals, anything likely needed for bring-up debug) identified and flagged for a dedicated test point footprint at layout.
- Polarity and pin-1 orientation for every polarized/asymmetric part confirmed against the actual footprint the symbol is linked to, not assumed from the symbol graphic alone.

## Layout review checklist

- Trace/space, annular ring, and drill sizes checked against the actual target fab's current capability table, not generic defaults.
- Global fiducials placed (2–3, diagonal, unobstructed) plus local fiducials near any fine-pitch (≤0.5 mm) part.
- Silkscreen reviewed visually with components placed — no text on pads, no illegible/overlapping text, polarity marks present and correctly oriented.
- Through-hole pads on large pours have thermal relief; SMD high-current/high-speed pads connect solidly without unnecessary added inductance.
- Tenting/via-in-pad handling specified explicitly and consistently with the design's intent (test points open, general vias tented, via-in-pad filled/capped where used).
- BOM and CPL exported directly from the finalized design, reference designators cross-checked for consistency across schematic/BOM/CPL, rotation convention checked against the assembler's guide for polarized parts.
- DRC run with fab-accurate constraints and all violations resolved or explicitly, deliberately excluded with a documented reason; ERC run and clean at the schematic stage.
- Fabrication outputs (Gerber + drill, or ODB++/IPC-2581) generated and spot-checked in a viewer before submission, alongside a written stackup/drill table for unambiguous fab interpretation.
