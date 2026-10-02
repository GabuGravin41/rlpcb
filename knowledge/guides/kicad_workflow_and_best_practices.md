---
title: KiCad Workflow and Best Practices
domain: digital
tags: [KiCad, schematic, PCB-layout, ERC, DRC, netclass, kicad-cli, kicad-python, hierarchical-sheets, differential-pairs]
applies_to: [general PCB, digital, high-speed]
---

## Project structure

- A KiCad project is a `.kicad_pro` file plus associated `.kicad_sch` (schematic, one root sheet minimum, more for hierarchical designs), `.kicad_pcb` (board layout), and library table files (`sym-lib-table`, `fp-lib-table`) — keep all of these together in one project folder; don't scatter schematic/PCB files across directories, since relative library paths and plot output paths assume the project structure.
- Use **version control (git)** on the project folder; KiCad's file formats (S-expression based since KiCad 6+) are git-diff-friendly compared to the old legacy format, making meaningful code review of schematic/PCB changes possible.
- Keep a project-local library table (rather than only global) when a design depends on project-specific custom symbols/footprints, so the project is portable to another machine without missing library references.

## Hierarchical sheets

- For any design beyond a single simple circuit, split the schematic into **hierarchical sheets** (Place → Hierarchical Sheet) — one sheet per functional block (power supply, MCU core, each major interface) rather than one flat, enormous schematic page.
- Each hierarchical sheet has **hierarchical pins** on its sheet symbol (in the parent sheet) corresponding to **hierarchical labels** inside that sheet — these connect nets across the sheet boundary explicitly and visibly, unlike global labels which connect implicitly by name-matching anywhere in the project.
- Reuse identical sub-circuits (e.g., multiple identical DDR byte-lane sheets, or multiple identical power supply channels) by instancing the same sheet file multiple times if your design has repeated blocks — KiCad supports multiple instances of one sheet file, each with independent reference designator annotation.

## Net labels vs global labels vs hierarchical labels

- **Local (net) label**: connects same-named wires only within the same schematic sheet — does not cross sheet boundaries even in a hierarchical design.
- **Global label**: connects same-named nets anywhere in the entire project, across any sheet, without needing a hierarchical pin/sheet-symbol connection — convenient for power/ground-like nets that need to reach many sheets, but can make the hierarchy's actual signal flow less visually explicit (a reviewer can't see the connection just from the sheet symbols).
- **Hierarchical label + hierarchical sheet pin**: the "correct," explicit way to pass a signal between a parent sheet and a child sheet — the connection is visible as a pin on the sheet symbol in the parent, making the hierarchy's actual interconnect traceable just by looking at sheet symbols.
- Practical convention: use hierarchical labels/pins for a sheet's actual functional I/O (what a datasheet block diagram would show as a wire between blocks), and reserve global labels for genuinely global nets (power rails, ground, and perhaps a small number of system-wide signals like a shared reset) — overusing global labels for ordinary signals defeats the readability benefit of having a hierarchy at all.

## Power symbols and PWR_FLAG

- Power symbols (e.g., `VCC`, `GND`, `+3V3`) are special symbols that implicitly create a global-label-like net connection to every instance of the same power symbol in the project.
- **ERC requires every power net to have a power source** — a power symbol alone is a power *input* pin type in ERC's model; ERC will flag a "power input not driven" style error unless something marks that net as actually being driven by a source.
- **PWR_FLAG**: a special symbol placed on a power net (commonly right at a regulator output or a connector's power pin) that tells ERC "this net is legitimately driven here," resolving the "unconnected power input" class of ERC error without needing an actual driving symbol/pin. Place one PWR_FLAG per electrically distinct power net that doesn't already have an explicit driver pin (e.g., a regulator's output pin, which ERC already treats as a power output, doesn't need one; a bare net fed only from an external connector often does).

## ERC — meaning of common errors

- **"Pin not connected"**: a pin with no explicit net/label attached and no "no connect" flag placed — either wire it, label it, or explicitly mark it with a No-Connect flag (Place → No Connect Flag) if intentionally unused, so ERC and later reviewers know it wasn't simply forgotten.
- **"Conflict between driver pins"**: two output-type pins tied to the same net (e.g., two IC outputs directly wired together without a shared-bus/tri-state understanding) — usually a real design error unless deliberately intended (e.g., a properly designed open-drain/open-collector bus, in which case pin electrical type should be set to reflect that rather than plain "output").
- **"Power input not driven"**: a power-type pin with no PWR_FLAG or driving output pin on its net — resolve with a PWR_FLAG or by checking that the intended driving pin (e.g., regulator output) is actually connected to the same net name.
- **"Unannotated symbol"**: a symbol without a final reference designator (still showing `?`, e.g., `U?`, `R?`) — run annotation (Tools → Annotate Schematic) before proceeding to layout/BOM export.
- Treat every ERC warning/error as something to resolve or deliberately, visibly suppress (KiCad supports per-violation exclusions with a note) rather than ignore — a clean ERC run is a prerequisite for a trustworthy netlist going into layout.

## Annotation

- **Annotate Schematic** (Tools → Annotate Schematic) assigns final reference designators (R1, C1, U1, etc.) based on your chosen scheme (sheet-number-based blocks, e.g., 100-199 for sheet 1, is a common convention for large hierarchical designs to avoid renumbering collisions as sheets are added/removed).
- Re-run annotation any time new symbols are added, and use "keep existing annotations" mode once a design is stable so previously-assigned reference designators (which may already appear on a physical prototype's silkscreen) don't shuffle unexpectedly.

## Footprint assignment

- Use the **Symbol/Footprint Assignment tool** (formerly "CvPcb," now integrated as Tools → Assign Footprints in recent KiCad) to link each schematic symbol to a specific PCB footprint from a footprint library.
- Confirm footprint correctness against the actual component's mechanical datasheet (pad pitch, pad size, courtyard) — do not trust a footprint name alone; visually inspect it in the footprint editor/3D viewer, especially for connectors and any part with pin-1/polarity significance, since a wrong or mirrored footprint is a common and costly (re-spin-triggering) mistake.

## Symbol/footprint libraries and library tables

- **sym-lib-table**: defines which symbol libraries (and their file paths/nicknames) are available to a project — exists at both global (user-wide) and project-local scope; project-local entries let a design travel with its own custom libraries.
- **fp-lib-table**: the same concept for footprint libraries.
- When creating custom parts, maintain a project-local (or team-shared, version-controlled) library rather than only relying on system-global libraries that won't travel with the project to another machine or teammate — a design that depends on undocumented local-only libraries is not reproducible.

## Netclasses

- **Board Setup → Design Rules → Net Classes** defines groups of nets sharing common electrical rules: trace width, clearance, via size/drill, and (for differential pairs) diff-pair gap/width.
- Assign nets to net classes either by explicit net-class assignment in the schematic (via net class directives) or by pattern-matching rules; use net classes to enforce, for example, a wider trace/heavier clearance for power nets, a specific width/gap for each controlled-impedance interface (USB, Ethernet, PCIe, DDR — see `high_speed_signal_integrity.md` and `interfaces_usb_ethernet_pcie_ddr.md` for target values), and tighter clearance for high-voltage nets per IPC-2221B.

## Custom design rules (.kicad_dru)

KiCad supports a text-based custom rules file (`<project>.kicad_dru`) for rules beyond what the net-class UI covers — e.g., conditional rules based on layer, net class combination, or component courtyard proximity. Basic syntax example:

```
(version 1)

(rule "HV clearance"
   (condition "A.NetClass == 'HV_400V'")
   (constraint clearance (min 1.5mm)))

(rule "DDR byte lane length match"
   (condition "A.inDiffPair('DDR_DQ0') || A.inDiffPair('DDR_DQ1')")
   (constraint length (min 20mm) (max 22mm)))

(rule "No via under BGA"
   (layer "F.Cu")
   (condition "A.insideCourtyard('U1')")
   (constraint via_count (max 0)))
```

Each rule has a `condition` (an expression selecting which items it applies to) and one or more `constraint` clauses (clearance, track width, length, via count, hole size, etc.). Use this file for rules that a simple net-class definition can't express, such as conditional clearance around a specific high-voltage component, or a courtyard-based via-keepout under a BGA package. Keep the rules file in version control alongside the project.

## Differential pairs

- Name P/N nets with a consistent, KiCad-recognized suffix pattern (`_P`/`_N`, or `+`/`-`) so the router's differential-pair mode auto-detects the pair.
- Use **Route → Differential Pair** (or the toolbar's diff-pair routing icon) to route both legs together with a maintained gap; set the target gap/width via the net class or a `.kicad_dru` rule matched to the pair's impedance target.
- Use the **length-tuning** tools (accessible in the interactive router, typically via a keyboard shortcut or toolbar icon for "Tune length" / "Tune differential pair skew") to add serpentines matching the interface's matching requirements (see `high_speed_signal_integrity.md`).

## Interactive router modes

- **Shove**: pushes existing traces out of the way as a new trace is routed through them, keeping connections intact — useful for dense boards where traces need to be nudged rather than manually rerouted.
- **Walkaround**: routes the new trace around existing obstacles without disturbing them — useful when you don't want to perturb already-tuned/length-matched traces.
- **Highlight collisions (or "off")** mode simply flags overlaps without automatically resolving them, useful when you want full manual control.
- Switch modes contextually: shove/walkaround for general routing efficiency, highlight-only mode when working near carefully tuned high-speed traces you don't want the router auto-adjusting.

## Teardrops

- A **teardrop** is a gradual copper widening at the junction between a trace and a pad/via, reducing stress concentration (useful for mechanical reliability, particularly on boards subject to flex/vibration) and slightly improving the transition's electrical/manufacturing (acid-trap avoidance) characteristics.
- KiCad supports adding teardrops per-pad/via or globally (right-click → Teardrops, or a board-wide filter) since KiCad 7+ — apply them especially on connector pads, high-reliability boards (see `aerospace_defense_and_high_reliability.md`), and vias in high-current paths.

## Zones and fills

- Create **copper zones** (Place → Zone) for ground/power pours; assign each zone to a specific net and layer, and set clearance, thermal relief style (see `dfm_dfa_fabrication_and_assembly.md`), and minimum zone width appropriately per net class.
- **Fill/refill zones** (B shortcut, or Edit → Fill All Zones) after routing changes — zones do not automatically update live in all KiCad versions/settings, so always refill and visually inspect before generating DRC/fab outputs, since an unfilled or stale zone can hide a DRC issue or leave an unintended gap in a reference plane.
- Check zone priority ordering when multiple zones on the same layer might overlap (e.g., a small keepout pour inside a larger ground pour) — zone priority determines which one "wins" in the overlap area.

## Stackup editor

See `stackup_and_layer_count.md` for full stackup guidance — in KiCad, this lives under **Board Setup → Physical Stackup**, where each layer's material, thickness, and Dk/Df are defined, feeding the impedance calculator used to size controlled-impedance net classes.

## 3D viewer

- Use **View → 3D Viewer** to visually verify component placement, check for mechanical interference (connector overhang past the board edge, tall components colliding with an enclosure or heatsink), and catch obviously wrong/mirrored footprints before committing to fabrication.
- Assign accurate 3D models to footprints (many manufacturer/library sources provide STEP models) so the 3D check is actually meaningful rather than showing placeholder boxes.

## Plotting fabrication outputs

- **File → Plot** (or Fabrication Outputs) generates Gerbers per layer; **File → Fabrication Outputs → Generate Drill Files** produces the Excellon drill file(s) and drill map; recent KiCad versions also offer direct **ODB++** and **IPC-2581** export from the same menu area — see `dfm_dfa_fabrication_and_assembly.md` for format tradeoffs.
- Always generate a **drill/layer legend and a stackup drawing** alongside the Gerbers (either exported from the stackup editor or hand-documented) so the fab has an unambiguous reference for hole-to-layer-pairing and material stack, rather than relying on Gerber files alone to convey that information.

## kicad-cli commands

KiCad 7+ ships a command-line tool (`kicad-cli`) enabling scripted/CI-driven exports and checks without opening the GUI — useful for automated build pipelines or batch-regenerating outputs after every commit. Common subcommands:

```
kicad-cli sch export netlist project.kicad_sch
kicad-cli sch erc project.kicad_sch --output erc_report.json
kicad-cli pcb drc project.kicad_pcb --output drc_report.json
kicad-cli pcb export gerbers project.kicad_pcb --output gerbers/
kicad-cli pcb export drill project.kicad_pcb --output gerbers/
kicad-cli pcb export step project.kicad_pcb --output board.step
kicad-cli pcb export pos project.kicad_pcb --output placement.pos
kicad-cli pcb export bom project.kicad_pcb --output bom.csv
```

These enable a CI check (e.g., a git pre-commit or CI pipeline step) that fails the build if ERC/DRC report unresolved violations — a strong practice for team or long-lived projects, catching regressions the moment they're introduced rather than at the next manual review.

## IPC API (kicad-python) and plugins

- KiCad 9+ introduces an official **IPC API** (an inter-process communication API allowing external scripts/plugins to query and modify a running KiCad session programmatically), with a Python binding (`kicad-python`) — this supersedes the older SWIG-based `pcbnew` scripting API for many new use cases, offering a more stable, versioned interface for automation (bulk footprint placement, custom design-rule checking scripts, BOM/CPL post-processing, generative layout helpers).
- Plugins (Action Plugins, installable via KiCad's Plugin and Content Manager/PCM) extend the GUI directly — useful for repeatable custom operations (e.g., a specific company's silkscreen-stamping convention, a custom copper-pour post-processor) beyond what built-in tools cover.
- When writing automation against a design an AI copilot or script will modify programmatically, prefer the IPC API/kicad-python where available for its more stable versioning guarantees over directly manipulating file-format internals.

## Essential keyboard shortcuts

| Key | Action (context) |
|---|---|
| `A` | Add symbol (schematic) / Add footprint (PCB) |
| `W` | Draw wire (schematic) |
| `L` | Add label (schematic) |
| `P` | Add power symbol (schematic) |
| `E` | Edit selected item's properties |
| `M` | Move (schematic/PCB) |
| `G` | Drag (keeps connections, PCB) |
| `R` | Rotate |
| `X` | Mirror horizontally (footprint/PCB) — note: also historically used as a route/track-start shortcut context in some KiCad versions, confirm current binding in your version's hotkey list |
| `Y` | Mirror vertically |
| `V` | Add via (while routing, PCB) |
| `D` | Drag track keeping 45°/90° routing constraint (PCB, version-dependent binding) |
| `B` | Fill all zones (PCB) |
| `Ctrl+M` | Move exact (precise numeric move, version-dependent) |
| `Delete` | Delete selected item |

Hotkeys have shifted slightly across KiCad 6/7/8/9 releases — always check **Preferences → Hotkeys List** (searchable) in the version actually installed rather than assuming an older version's binding, and consider exporting/sharing a consistent hotkeys preset across a team for muscle-memory consistency.

## Quick reference: ERC error meanings

| ERC message | Likely meaning | Typical fix |
|---|---|---|
| Pin not connected | Pin has no wire/label, no NC flag | Wire it, label it, or add No-Connect flag |
| Conflict between driver pins | Two outputs tied to same net | Fix wiring, or set pin type to open-collector/tri-state if intentional |
| Power input not driven | No PWR_FLAG or driving pin on net | Add PWR_FLAG or check driving pin's net name |
| Unannotated symbol | Reference still shows `?` | Run Annotate Schematic |
| Label not connected to anything | Orphan label with no matching net elsewhere | Check spelling/typo, or remove if unused |

## Quick reference: label type usage

| Label type | Scope | Best used for |
|---|---|---|
| Local (net) label | Same sheet only | Same-sheet net naming/readability |
| Global label | Entire project, any sheet | Power/ground-like universally shared nets |
| Hierarchical label + sheet pin | Explicit parent-child connection | Genuine sheet-to-sheet signal flow |

## Quick reference: kicad-cli command summary

| Command | Purpose |
|---|---|
| `kicad-cli sch erc` | Run ERC from command line, output report |
| `kicad-cli sch export netlist` | Export netlist for external tools |
| `kicad-cli pcb drc` | Run DRC from command line, output report |
| `kicad-cli pcb export gerbers` | Generate Gerber fabrication files |
| `kicad-cli pcb export drill` | Generate Excellon drill files |
| `kicad-cli pcb export step` | Export 3D STEP model |
| `kicad-cli pcb export pos` | Export component placement (CPL) file |
| `kicad-cli pcb export bom` | Export bill of materials |

## Quick reference: essential shortcuts by workflow stage

| Stage | Shortcut | Action |
|---|---|---|
| Schematic capture | A | Add symbol |
| Schematic capture | W | Draw wire |
| Schematic capture | L | Add label |
| Schematic capture | P | Add power symbol |
| PCB placement | A | Add footprint |
| PCB placement | M | Move |
| PCB placement | R | Rotate |
| PCB placement | Y | Mirror vertically |
| PCB routing | V | Add via |
| PCB routing | G | Drag (keep connections) |
| PCB finishing | B | Fill all zones |

## Common mistakes

- Leaving unannotated symbols (`U?`, `R?`) or unresolved ERC errors before moving to layout, producing a netlist that silently omits or misconnects nets.
- Using global labels for every signal instead of hierarchical pins, making the schematic hierarchy's actual data flow invisible to a reviewer.
- Forgetting a PWR_FLAG on a net that genuinely needs one, chasing a false "not driven" ERC error, or conversely adding one where an existing driver pin already satisfies ERC and masking a real missing-connection bug.
- Not refilling zones after a late routing change, shipping Gerbers with a stale/incorrect copper pour.
- Trusting a footprint name without visually verifying pad layout/courtyard/3D model against the actual component datasheet.
- Skipping version control on the project, losing the ability to see what changed between review cycles or recover a previous working state.
- Relying only on GUI DRC/ERC for a long-lived project without wiring `kicad-cli` checks into a CI step, letting regressions slip through between manual reviews.

## Schematic review checklist

- Annotation complete (no `?` reference designators), ERC clean or every remaining item explicitly, deliberately excluded with a note.
- Hierarchical labels/pins used for genuine sheet-to-sheet signal flow; global labels reserved for truly global nets (power, ground, system-wide resets).
- Every power net has either a driving output pin or an explicit PWR_FLAG.
- Every symbol linked to a footprint verified in the footprint assignment tool, cross-checked against the actual component datasheet.
- Net classes (or a plan for them) identified for every controlled-impedance or special-clearance interface before moving to layout.

## Layout review checklist

- Stackup configured in Board Setup matching the actual target fab (see `stackup_and_layer_count.md`); net classes and any `.kicad_dru` custom rules assigned per interface.
- Differential pairs recognized correctly (P/N suffixes) and routed with the router's diff-pair mode, gap matching the impedance calculator's output.
- Zones filled (not stale) and visually inspected layer by layer; zone priority correct where zones overlap.
- 3D viewer checked for mechanical interference and gross footprint/orientation errors before fab output.
- DRC run with fab-accurate constraints, all violations resolved or explicitly excluded; ERC re-confirmed clean if any late schematic changes were made.
- Fabrication outputs (Gerber/drill or ODB++/IPC-2581) generated via a repeatable process (GUI plot dialog or `kicad-cli`) and spot-checked before submission.
- Project (including any custom libraries and `.kicad_dru` file) committed to version control at the release point so the exact fabricated state is reproducible later.
