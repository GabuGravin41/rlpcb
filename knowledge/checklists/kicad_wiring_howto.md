---
title: KiCad Wiring How-To for Beginners
domain: digital
tags: [kicad, schematic editor, wiring, hotkeys, hierarchical sheets, annotation, footprints, erc, pcb editor, routing, drc]
applies_to: [first-time kicad users, schematic capture walkthrough, pcb layout walkthrough]
---

## Before you start

This is a step-by-step walkthrough for someone new to KiCad's schematic and PCB editors, covering the mechanical "how do I actually draw this" questions that trip up beginners even after they understand the electrical design itself. It complements kicad_workflow_and_best_practices.md, which covers project structure, netclasses, and advanced workflow — read this first if you've never wired a schematic in KiCad before, then read that guide for the broader practices. Hotkeys given here match current KiCad 8/9 defaults; if a key doesn't do what's described, check **Preferences → Hotkeys List** (searchable) in your installed version — hotkeys have shifted slightly across releases, and the menu path is always a reliable fallback (given alongside each hotkey below).

## Placing symbols

1. In the schematic editor, press **A** (or **Place → Add Symbol**) to open the symbol chooser, search for the part, and click to place it. Press **Escape** to stop placing after the last one you need.
2. Each placed symbol starts unannotated (shows `U?`, `R?`, etc.) — this is normal at this stage; you'll annotate later (see Annotation below) once the schematic is more complete.
3. Rotate a selected symbol with **R** (Place → rotate, or right-click → Rotate), mirror horizontally with **X** and vertically with **Y** (right-click → Mirror also works) — use these to orient a symbol so its pins face the direction you want to wire from, rather than fighting an awkward wire routing around a symbol placed backward.

## Drawing wires

1. Press **W** (or **Place → Wire**) to start wiring. Click on a pin's end (the small circle at the tip of the pin) to start a wire from it, click again to place a corner/bend, and click on the destination pin's end to finish. Press **Escape** to stop wiring.
2. **How to be sure a wire actually connected**: an unconnected pin shows as a small circle (or a colored dot, depending on your KiCad version/theme) at its tip. Once a wire is properly connected to that pin, **the circle disappears** — the pin end and the wire end merge visually into a single point with no gap and no circle. If you finish a wire near a pin but the circle is still visible, the wire did not connect — zoom in and try again, clicking precisely on the pin's endpoint.
3. **Avoiding floating/dangling wires**: a wire segment that ends in open space (not on a pin, not on another wire, not on a label) is a dangling wire — ERC will flag it, but don't rely on ERC alone; visually check that every wire endpoint terminates on something. A common beginner mistake is drawing a wire that visually crosses another wire without actually connecting to it — two wires crossing on screen are **not** electrically connected unless a **junction** (a solid dot) is placed at the crossing point.
4. **Junctions**: press **J** (or **Place → Junction**) to explicitly place a junction dot at a point where wires should connect — KiCad auto-places a junction dot when you draw a wire that starts or ends exactly on another wire's midpoint, but when in doubt (especially after moving wires around), place one explicitly so the connection is visually and electrically unambiguous. Two wires crossing at a T or X without a junction dot are not connected — this is one of the most common sources of a "the schematic looks right but the netlist is wrong" bug.
5. Use **M** (Move) to reposition a symbol or label while keeping attached wires connected as much as the editor can manage, or **G** (Drag) which keeps connections live and stretches attached wires along with the moved item — G is usually the better choice mid-schematic once things are already wired, since it preserves connectivity more predictably than a plain Move followed by re-wiring.

## Labels: local, global, and power symbols

- Press **L** (or **Place → Add Label**) for a local net label — connects same-named wires only within the same schematic sheet.
- Press **Ctrl+L** (or **Place → Add Global Label**) for a global label — connects same-named nets anywhere in the project across any sheet, useful for power-adjacent or genuinely global signals. See kicad_workflow_and_best_practices.md for when to prefer this over a hierarchical label.
- Press **P** (or **Place → Add Power Symbol**) to place a power symbol (`GND`, `+3V3`, `+5V`, etc.) — these behave like an implicit global label for that exact net name, connecting to every other instance of the same power symbol in the project.
- Label text must match exactly (including case, in most configurations) for two labels to be considered the same net — a typo between `+3V3` and `+3v3` on different sheets creates two separate, unconnected nets that look identical at a glance.

## No-connect flags

- Press **Q** (or **Place → Add No Connect Flag**) to mark a pin as deliberately left unconnected — this places an X-shaped flag on the pin and tells ERC this is intentional, not a forgotten connection. Use this on every pin you genuinely don't need to wire (an unused GPIO you're not using, an optional feature pin) so ERC's "pin not connected" warning only ever flags real mistakes, not expected unused pins.

## Editing and moving

- Press **E** (or double-click most items, or right-click → Edit Properties) to edit a selected item's properties — for a symbol this opens its field editor (reference designator, value, footprint assignment); for a wire or label it opens relevant properties like line style or label text.
- Press **M** for Move (breaks connections at the item's old position, wires stay put unless also selected) or **G** for Drag (keeps connections attached, stretching wires as the item moves) — as a rule of thumb, use G once you have real wiring you don't want to have to redo, and M mainly for initial rough placement before wiring anything.
- Press **R** to rotate and **X**/**Y** to mirror a selected item, same as during initial placement.

## Hierarchical sheets and hierarchical labels

1. For any design beyond a single simple page, use **Place → Hierarchical Sheet** to draw a sheet symbol on the parent (root) sheet, giving it a name and a target sheet file — double-click into it to start drawing the actual circuit for that functional block.
2. Inside the child sheet, place **hierarchical labels** (Place → Hierarchical Label) for every signal that needs to reach the parent sheet or a sibling sheet — each hierarchical label automatically creates a corresponding pin on the sheet symbol back on the parent sheet.
3. On the parent sheet, wire each sheet symbol's pin like any other pin — this is the explicit, visible way signals cross between hierarchical sheets, in contrast to a global label's implicit anywhere-in-project connection. See kicad_workflow_and_best_practices.md for when to prefer hierarchical vs. global labels.
4. If you rename or add a hierarchical label inside a child sheet, the parent sheet's sheet-symbol pin list needs to be refreshed (KiCad usually does this automatically when you reopen/refresh the parent sheet view, but double-check the sheet symbol's pin list matches the child sheet's hierarchical labels exactly before annotating).

## Annotation

- Once symbols are placed (wiring can be in progress or complete), run **Tools → Annotate Schematic** to assign final reference designators (turning `R?` into `R1`, `U?` into `U1`, etc.).
- Re-run annotation any time you add new symbols; use the "keep existing annotations" option once a design is stable so parts you've already referenced elsewhere (a BOM, a physical prototype's silkscreen) don't get renumbered unexpectedly.

## Assigning footprints

1. Open **Tools → Assign Footprints** (the footprint assignment tool) after annotation, and link each schematic symbol to a specific PCB footprint from a footprint library.
2. Don't trust a footprint name alone — open it in the footprint viewer and visually check pad pitch, pad size, and courtyard against the actual component's mechanical datasheet, especially for connectors and anything with pin-1/polarity significance.
3. A symbol with no footprint assigned will block PCB synchronization (Update PCB from Schematic) or, worse, silently produce an incomplete board — verify every symbol shows an assigned footprint before moving on.

## Running ERC

1. Run **Inspect → Electrical Rules Checker** (or the ERC toolbar icon) before moving to the PCB — this checks for unconnected pins, driver conflicts, undriven power nets, and unannotated symbols.
2. Review every reported item individually. Fix real problems (wire a forgotten pin, add a missing PWR_FLAG per kicad_workflow_and_best_practices.md, add a No-Connect flag on a genuinely unused pin) rather than blanket-dismissing warnings.
3. Aim for a clean ERC run (zero unresolved violations) before generating the netlist for layout — a schematic with unresolved ERC errors going into layout usually means real missing or wrong connections will show up as confusing PCB-side problems later.

## Moving to the PCB: Update PCB from Schematic

1. Once the schematic is wired, annotated, footprint-assigned, and ERC-clean, open the PCB Editor and press **F8** (or **Tools → Update PCB from Schematic**) to synchronize the board with the schematic's netlist.
2. Review the dialog's change list before applying — it will show new footprints to add, footprints to remove (if you deleted a symbol), and net changes — catching an unexpected large "remove" list here is a good moment to check you didn't accidentally break something in the schematic.
3. Re-run F8 any time you change the schematic (add/remove a symbol, change a net connection) — the PCB does not automatically stay in sync; you must explicitly re-import each time.

## Placing footprints on the PCB

1. Newly imported footprints appear stacked near the board origin (or off to one side) — select and move each one (**M** to move, **R** to rotate, **X**/**Y** to mirror to the opposite side of the board) into its intended position.
2. Use ratsnest lines (the thin airwires connecting related pads) as a placement guide — arrange footprints so ratsnest lines are short and don't cross excessively, which generally correlates with an easier, shorter routing job later.
3. Group functionally related footprints (a regulator and its input/output capacitors, a connector and its adjacent ESD protection) physically close together before routing, following the placement principles in layout_review_checklist.md.

## Routing traces

1. Press **X** (or click the route-tracks toolbar icon) to start routing a track from a pad or an existing track. Click to place corners, click on the destination pad to finish, and press **Escape** to stop.
2. While routing, press **V** to place a **via** — switches the track to a different layer at that point (useful for routing around obstacles on the other side of the board); select the target layer either from the via's layer-pair setting or a layer-selection popup depending on your KiCad version.
3. Watch the cursor's ratsnest and DRC-violation highlighting (if enabled) while routing — a track that would violate clearance rules or create a short is typically highlighted in real time, letting you correct course immediately rather than discovering it later in a full DRC run.
4. Use the interactive router's **shove** mode (pushes existing tracks aside) for general routing efficiency on a dense board, or **walkaround** mode when you don't want to disturb already-placed, carefully-tuned traces — see kicad_workflow_and_best_practices.md for when to use each.

## Differential pairs and length tuning

1. Name paired nets with a recognized suffix (`_P`/`_N` or `+`/`-`) so KiCad auto-detects them as a differential pair.
2. Press **6** (or select the Differential Pair routing tool from the toolbar) to route both legs of a pair together with a maintained gap, set via the net class or a `.kicad_dru` custom rule matched to the interface's target impedance (see high_speed_signal_integrity.md).
3. Press **7** (or select the Length Tuning tool) to add serpentine meanders that bring a track (or a differential pair's skew) into the length-matching tolerance your interface requires — set the target length/tolerance in the tool's settings dialog before tuning, and watch the live length readout as you drag to build the serpentine.

## Zones and copper pours

1. Press **Ctrl+Shift+Z** (or **Place → Zone**) to draw a copper zone (commonly a ground or power pour) — draw its outline, then assign it to a specific net and layer, setting clearance and thermal-relief style in the zone properties dialog.
2. Zones do not fill live as you draw or as the board changes — press **B** (or **Edit → Fill All Zones**) to fill (or refill) every zone after any routing change, and do this before every DRC run or fabrication export, since a stale/unfilled zone can hide a real issue or leave an unintended gap in a reference plane.
3. Visually inspect filled zones layer by layer after refilling — check zone priority (which zone "wins" where two zones on the same layer overlap) if you have nested or adjacent zones with different clearance/net requirements.

## Running DRC

1. Run **Inspect → Design Rules Checker** (DRC) after routing is complete (and zones refilled) — this checks clearance, track width, via size, unrouted nets, and any custom `.kicad_dru` rules against your configured stackup and net classes.
2. Set up **Board Setup → Design Rules → Net Classes** (and stackup under **Board Setup → Physical Stackup**) to match your actual target fabricator's capability before running DRC — running DRC against KiCad's generic defaults instead of your fab's real minimums can pass a board the fab would actually reject, or needlessly fail one it would happily manufacture.
3. Review every violation individually; fix real problems and use per-violation exclusions (with a note explaining why) only for deliberate, reviewed exceptions — never blanket-suppress the whole violation list.
4. Confirm the unrouted-net count is zero and visually scan for any remaining ratsnest/airwire lines before considering the board complete.

## Plotting fabrication outputs

1. Use **File → Plot** (or **File → Fabrication Outputs → Gerbers**) to generate Gerber files per layer, and **File → Fabrication Outputs → Generate Drill Files** for the Excellon drill file and drill map.
2. Recent KiCad versions also offer direct **ODB++** and **IPC-2581** export from the same fabrication-outputs menu area — see fab_order_checklist.md for choosing between these and Gerber+drill based on what your fabricator expects.
3. Open the exported Gerbers in a viewer separate from KiCad (many fab houses provide an online Gerber viewer, or use a standalone tool) before submitting — this catches export-step mistakes that wouldn't be visible from inside KiCad's own view.

## Common beginner mistakes

- Drawing wires that visually cross without a junction dot, producing a schematic that looks connected but isn't electrically joined.
- Leaving a wire endpoint floating in open space rather than terminating it on a pin, label, or junction.
- Confusing local labels (same-sheet only) with global labels (whole-project), causing either an unintended cross-sheet short or a signal that fails to connect where expected.
- Forgetting to re-run F8 (Update PCB from Schematic) after a late schematic change, leaving the PCB editor working from a stale netlist.
- Leaving zones unfilled (or stale after a routing change) before generating DRC or fabrication outputs.
- Trusting a footprint's name without visually checking its pad layout and courtyard against the real component's datasheet.
- Running DRC/ERC against generic default rules instead of the values matching your actual target fabricator and design's electrical requirements.
