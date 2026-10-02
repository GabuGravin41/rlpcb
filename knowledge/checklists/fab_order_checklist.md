---
title: Fabrication Order Checklist
domain: general
tags: [gerbers, drill files, ipc-2581, bom, cpl, jlcpcb, pcbway, stackup, impedance, panelization, fab order]
applies_to: [pcb fabrication ordering, assembly ordering, jlcpcb, pcbway, gerber export]
---

## How to use this checklist

Run this immediately before submitting a fabrication/assembly order, after the layout review checklist has already passed. This checklist is specifically about the export/order-package correctness and the specification choices communicated to the fab/assembly house — errors here are often invisible in the CAD tool and only surface as a wrong or unusable board weeks later.

## File package: Gerbers and drill

- [ ] Gerber files exported for every copper layer, solder mask (top and bottom), silkscreen (top and bottom), and paste (top and bottom, if ordering assembly) — verify layer count matches the intended stackup exactly, with no missing or extra layer.
- [ ] Gerber format specified explicitly (RS-274X / Gerber X2 is the modern standard most fabs expect) rather than relying on a tool default that may not match the fab's expected format.
- [ ] Drill files exported separately for plated (PTH) and non-plated (NPTH) holes, in the format the specific fab expects (Excellon is standard; verify units — inch vs. mm — match what's declared).
- [ ] A drill legend/map file included so hole sizes are unambiguous to the fab, especially when multiple distinct hole sizes are used.
- [ ] Board outline (Edge.Cuts or equivalent mechanical layer) present and forms a single clean closed contour, with any internal cutouts/slots as separate closed contours — an open or duplicated outline is a common cause of a fab quoting or manufacturing the wrong board shape.
- [ ] Gerber preview opened in a viewer independent of the design tool (many fabs provide an online Gerber viewer, or use a standalone tool) to catch export-step errors before submitting.

## Alternative: IPC-2581 / ODB++

- [ ] Where the fab supports it, consider IPC-2581 or ODB++ as a single unified data package instead of separate Gerber/drill/stackup files — reduces the chance of a mismatch between individually-exported files (e.g., a stackup note that doesn't match the actual Gerber layer order), though most small-prototype-volume fabs (JLCPCB, PCBWay at typical prototype tiers) still primarily expect Gerber+drill; verify the specific fab's preferred format before choosing.
- [ ] If submitting IPC-2581, verify the exporting tool's IPC-2581 output has been validated against at least one known-good order with that specific fab, since export-tool IPC-2581 compliance has historically varied in completeness across CAD tools.

## Stackup and impedance documentation

- [ ] A stackup drawing/table (layer order, material, thickness per layer, copper weight per layer) included in the order package or communicated directly to the fab, especially for any board with controlled-impedance requirements.
- [ ] Controlled-impedance nets and their target impedance explicitly called out to the fab (a separate impedance-control document or clearly annotated stackup) — do not assume the fab will infer impedance requirements from trace width alone.
- [ ] For a multi-lamination HDI stackup, the build-up sequence (which layers are laser-drilled microvias, which are mechanically drilled through-holes, stacked vs. staggered via structure) explicitly specified, since this materially affects both cost and manufacturability — see bga_fanout_and_gpu_class_boards.md.
- [ ] Surface finish specified (HASL, ENIG, OSP, immersion silver/tin, etc.) appropriate for the component pitch and any specific requirement (ENIG is commonly required for fine-pitch BGA/QFN for planarity; gold-finger edge connectors need a specific ENIG or hard-gold spec).
- [ ] Minimum trace/space, minimum via size, and minimum annular ring in the design verified against the fab's stated capability for the requested service tier (standard vs. advanced/HDI) before submission, not discovered from a DFM-check rejection after order.

## BOM (Bill of Materials)

- [ ] BOM includes, at minimum: reference designator, manufacturer part number, manufacturer name, quantity, and a clear description for every populated component — an assembly house cannot reliably source or verify a part from a generic description alone.
- [ ] BOM cross-checked against the schematic for completeness — every populated reference designator in the design appears in the BOM, and every BOM line corresponds to an actual populated component (no orphaned lines for since-removed parts).
- [ ] DNP (do-not-populate) components clearly marked as DNP in the BOM, consistent with the schematic's DNP marking (see schematic_review_checklist.md) — an assembly house will otherwise either try to source and place a DNP part or, worse, silently skip a part that should have been populated.
- [ ] Alternate/substitute part numbers provided where the primary part has known supply-risk (common practice given ongoing component shortage volatility), with the alternate verified as a true form/fit/function match, not just a similar-sounding part.
- [ ] Lead-free/RoHS compliance status confirmed for every part if the target market requires it.

## CPL (Component Placement List / Pick-and-Place file)

- [ ] CPL includes reference designator, X/Y position, rotation, and layer (top/bottom) for every component to be placed by the assembly house.
- [ ] Rotation convention verified against the specific assembly house's expected reference (0° orientation convention varies between tools/fabs and is a very common source of components placed 90°/180°/270° off from intended) — many fabs (JLCPCB, PCBWay) publish their expected rotation reference per common footprint family; check polarized parts (diodes, electrolytic caps, ICs with a pin-1 indicator) specifically against this.
- [ ] CPL origin/coordinate system matches the Gerber files' origin so placement data aligns correctly with the actual board — a mismatched origin silently shifts every component's intended position.
- [ ] Fine-pitch or unusual-footprint parts double-checked visually in the CAD tool's assembly-preview/3D view against the CPL-derived placement before submission.

## Panelization

- [ ] If the fab or assembly process requires panelization (multiple board copies on one panel for efficient handling/assembly), panel array, spacing, and breakout method (v-score or mouse-bite/tab-route) specified explicitly — v-score suits straight-edge boards, tab-route/mouse-bites suit irregular outlines or boards needing a fully separable clean edge without a score line.
- [ ] Panel rail width and any required tooling holes/fiducials on the panel rail (not just on each individual board) included per the assembly house's requirement.
- [ ] Panelization reviewed for component clearance to the panel breakout line/mouse-bites, avoiding components too close to a break point that could be mechanically stressed during depaneling.
- [ ] If self-panelizing in the CAD tool rather than requesting the fab panelize, verify the exported panel Gerbers/drill match the intended array exactly (a common silent error).

## What to specify to the fab (order form / notes)

- [ ] Layer count, board thickness, copper weight, surface finish, solder mask color, silkscreen color — every board-level specification explicitly stated, not left to the fab's default (which varies by fab and can silently differ from what the design assumed, especially for board thickness and copper weight assumptions baked into an impedance calculation).
- [ ] Minimum trace/space and minimum via size mentioned if the design pushes close to the fab's stated capability, so the fab's DFM check specifically flags any marginal feature rather than silently processing (or silently rejecting) the order.
- [ ] Any special process requirement (controlled impedance, blind/buried vias, via-in-pad with fill/plate-over, castellated edge-plating, controlled-depth routing) explicitly called out as a line-item note, since these often require a manual quote/review rather than the fab's standard automated pricing flow.
- [ ] For assembly orders: which side(s) to assemble, whether hand-solder parts (e.g., through-hole connectors) are included in the automated assembly or expected to be hand-soldered afterward, and any component orientation/rotation exceptions communicated directly if the standard CPL rotation convention doesn't apply to an unusual part.
- [ ] Quantity, turnaround time tier (standard vs. expedited), and whether functional/electrical test (flying-probe or bed-of-nails, if offered) is requested for the order.

## Final review before submission

- [ ] Order package (Gerbers, drill, BOM, CPL, stackup notes) all generated from the same, final, reviewed design revision — verify no file in the package is stale from an earlier revision (a common error when BOM/CPL are exported at a different time than Gerbers, after a late schematic change).
- [ ] File naming and archive organization clear enough that the specific design revision this order corresponds to can be unambiguously identified later (include a revision/date string in the archive name, not just "gerbers.zip").
- [ ] Order package uploaded to the fab's own DFM/preview tool (most fabs provide this) and any flagged issue reviewed before finalizing payment/submission, not just trusted blind.
- [ ] A copy of the exact submitted order package (Gerbers, BOM, CPL, and any notes/instructions given to the fab) archived alongside the design files, so the as-manufactured board can be reconciled against the as-designed intent later if a field issue arises.
