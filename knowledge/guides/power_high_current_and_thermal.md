---
title: High-Current PCB Design and Thermal Management
domain: power
tags: [ipc-2152, trace current, copper weight, thermal vias, heatsinking, mosfet paralleling, kelvin sensing, current sharing]
applies_to: [power boards, motor drives, industrial power supplies, high-current battery systems]
---

## Trace current capacity: IPC-2152 vs the old IPC-2221 charts

The classic IPC-2221 trace-width-vs-current charts (and the widely circulated "10 mil per amp" rule of thumb) are based on 1950s-era test data and are known to be conservative/inaccurate for modern thin, multi-layer boards. **IPC-2152** (2009) supersedes it with data that accounts for board thickness, layer count, adjacent copper pours, and via proximity, and is the current industry-standard reference.

- IPC-2152 shows that internal traces need significantly more copper cross-section than external traces for the same current and temperature rise (internal layers dissipate heat less effectively — often 2x or more width needed vs an external trace for the same ΔT).
- Key inputs to any trace-current calculation: copper weight (oz/ft², i.e., thickness), trace width, allowed temperature rise (ΔT, commonly designed for 10–20°C rise above ambient for signal-adjacent traces, higher acceptable for dedicated power traces if thermal budget allows), and whether the trace is external (top/bottom) or internal.
- Do not rely on a single memorized number ("X amps per mm width") — use an IPC-2152-based calculator (many PCB tool vendors and Saturn PCB's freeware IPC-2152 calculator implement the full parametric model) with your actual copper weight, layer position, and ΔT target, and re-check when copper weight or ΔT budget changes.
- Practical starting points to sanity check calculator output (1 oz copper, external trace, 20°C rise): roughly 1 A per ~0.2–0.25 mm (8–10 mil) width for the classic conservative rule — real IPC-2152 external-trace figures are typically somewhat more generous than this old rule, and internal traces need roughly double the width of external for the same current/ΔT.

## Copper weight selection

- Standard PCB copper weights: 0.5 oz (17.5 µm), 1 oz (35 µm), 2 oz (70 µm), 3 oz, 4 oz, up to 6+ oz for dedicated power boards.
- Heavier copper (2 oz+) reduces required trace width for a given current and lowers resistive (I²R) losses and temperature rise — standard tradeoff against fabrication cost and minimum trace/space capability (heavy copper requires wider minimum trace/space due to etch undercut at high copper thickness; consult your fab's heavy-copper design rules, commonly a minimum trace/space of 6–8 mil for 2 oz, growing further for higher weights).
- For high-current power sections mixed with fine-pitch digital routing on the same board, consider "mixed" or "stepped" copper weight processes offered by some fabricators (thicker copper for power planes/traces, standard for fine-pitch signal layers), or dedicate specific layers to power distribution at higher copper weight.
- Doubling copper thickness roughly halves the required trace width for the same current/temperature-rise target (approximately, per IPC-2152's parametric relationship, not exactly linear).

## Copper pours and plane current distribution

- A wide copper pour/plane spreads current over a larger cross-section and improves thermal spreading (heat dissipates over more area) compared to a narrow trace, generally allowing more current for a given temperature rise — pours also lower DC resistance and inductance.
- Avoid "necking" a pour down to a narrow trace at a component pad or connector — the neck becomes the current-limiting/hot-spot point; keep entry/exit widths consistent with the pour's capacity, or explicitly calculate the neck as its own trace-current case.
- Slots, cutouts, or via fields inside a power pour reduce its effective cross-section locally — account for this when a plane has many vias/cutouts crossing the main current path (e.g., a BGA via field bisecting a power plane).
- For very high current (tens to hundreds of amps), consider multiple parallel planes on different layers, stitched together with a dense via array, rather than relying on a single plane layer.

## Thermal vias

Thermal vias conduct heat from a hot component (exposed-pad IC, power MOSFET, high-current connector) through the board to an internal or opposite-side copper plane/heatsink area.

- Standard thermal via: 0.3 mm (12 mil) drill, though smaller (0.2 mm) and larger (0.33–0.5 mm) are used depending on pad size and fab capability.
- Typical array density: vias spaced on a 1.0–1.2 mm grid under the thermal pad, as many as the pad area allows while maintaining fab minimum annular ring/spacing rules — datasheets for high-power ICs (e.g., integrated switching regulators) typically specify a recommended via count and pattern directly; follow it rather than guessing.
- **Via-in-pad with fill/plug and cap plating** is standard practice for thermal vias under fine-pitch or exposed-pad packages, to prevent solder wicking down the via during reflow (which causes voids and poor thermal/electrical contact) — this adds fabrication cost, so budget for it in DFM.
- Each unfilled open thermal via conducts less heat than a filled one and risks solder voiding; if cost-constrained and the via is not directly in the solder pad (i.e., in a nearby thermal relief area instead), unfilled vias are acceptable.
- Thermal resistance per via is roughly inversely proportional to via count for evenly spread vias — more vias roughly linearly reduces the parallel thermal resistance, but only up to the point where the destination copper plane itself becomes the bottleneck (increase destination copper area/thickness together with via count).

## Heatsinking

- Compute worst-case power dissipation P_diss for the component (conduction loss + switching loss for FETs, I²R for resistive elements, etc.).
- Junction temperature: Tj = Ta + P_diss × θJA (no heatsink) or Tj = Ta + P_diss × (θJC + θCS + θSA) with a heatsink (junction-to-case + case-to-sink interface + sink-to-ambient).
- Design target: keep Tj comfortably below the datasheet absolute max (typically 150°C for silicon power devices) — a common reliability-oriented design rule is to keep Tj ≤ 110–125°C at worst-case ambient and load, leaving margin for tolerance stack-up and aging, though exact margin depends on the application's reliability requirement (consumer vs industrial vs automotive).
- For board-mounted power devices without a discrete heatsink, the copper pour area itself is the heatsink — θJA scales strongly with copper area up to a point of diminishing returns (roughly the first 1–2 in² of copper gives the largest θJA improvement; beyond that, added copper area gives smaller incremental benefit) — check the specific package's datasheet θJA vs copper-area curve if available.
- Forced airflow (fan) dramatically reduces θSA/θCA compared to natural convection — factor this into thermal budget if the end product includes a fan, but never assume airflow will always be present in a design meant to also survive fan-failure or fanless operation modes.
- Thermal interface material (TIP: pads, grease) is required between a component and an external heatsink for any surface roughness/flatness gap — an air gap dramatically increases thermal resistance versus even modest TIM.

## MOSFET/switch paralleling for higher current

Paralleling MOSFETs increases effective current capacity and spreads I²R and switching losses across more silicon.

- **Static (DC) current sharing**: relies on matched Rds(on) between paralleled devices — Rds(on) has a positive temperature coefficient in power MOSFETs, which is self-stabilizing (a device carrying more current heats up more, its Rds(on) rises, pushing current to the cooler devices) — this natural thermal feedback is why MOSFET paralleling works reasonably well without active current-sharing circuitry, unlike paralleling bipolar transistors (which have negative tempco and need ballast resistors or active balancing to avoid thermal runaway in one device).
- **Dynamic (switching) current sharing**: gate drive symmetry matters a lot — use matched gate resistors and symmetric, low-inductance gate trace routing to each paralleled FET so they turn on/off at the same time; mismatched gate timing causes one device to carry disproportionate switching current/loss transiently, generating hot spots even if static sharing is fine.
- Physical layout: place paralleled FETs symmetrically around the current path (e.g., in a circle or line with equal-length connections to source/drain/gate busses) so parasitic inductance and thermal environment are as equal as possible between devices.
- Kelvin-connect the gate driver return separately from the high-current source path on each paralleled FET where possible (source-sense vs power-source) to avoid gate-drive timing errors caused by high di/dt voltage drop in the shared source trace.

## Kelvin (4-wire) current sensing

For any precision current measurement (shunt-based sensing, current-mode control feedback, protection thresholds), 2-wire sensing (measuring across the same pads that carry load current) includes connector, via, and trace resistance in the measurement, which is often comparable to or larger than the shunt resistance itself at low-value shunts.

- Route four separate connections to a shunt: two carrying load current (force), two dedicated sense traces tapped from inside the shunt's current pads (sense) going to the measurement amplifier/ADC.
- Sense traces should be a tightly coupled differential pair, routed away from high-current/high-di/dt paths to avoid inductive/capacitive noise pickup, and terminated directly at the amplifier's input pins (not via a shared plane).
- This applies equally to shunt-based current sensing in motor drives, battery packs (see power_battery_bms_ups.md), and buck/boost converter current-mode control feedback.

## Load sharing / current sharing between parallel supplies

When multiple power supplies (or supply modules) feed the same output bus in parallel for redundancy or higher total current, uncontrolled paralleling causes one supply to hog most of the current (due to small output voltage mismatches) while others idle or even sink current — this needs an explicit current-sharing scheme:

- **Droop sharing (passive)**: each supply's output impedance is intentionally increased slightly (via a small series resistance or a droop control loop that reduces output voltage slightly as load current increases) so that as one supply takes more current, its output droops, naturally pushing load to the others. Simple, no communication needed between supplies, but sacrifices some load regulation accuracy.
- **Active current sharing**: supplies communicate (via a shared analog "share bus" signal or digital communication) to actively equalize output current among modules — used in redundant industrial/telecom power systems (parallel PSU modules) and dedicated current-sharing/ORing controller ICs (e.g., LTC4370-style parts) that combine ideal-diode ORing with active current balancing between two or more input sources feeding a common output, commonly used for redundant N+1 power supply architectures.
- **Master-slave sharing**: one supply regulates output voltage; others regulate to match a current reference derived from the master — common in modular/multiphase supply architectures.
- For multiphase buck converters (many parallel phases feeding one high-current rail, common in CPU/GPU VRMs), current sharing is handled internally by the multiphase controller IC — the layout requirement is symmetric phase layout (equal trace lengths/impedances from each phase to the shared output) so the controller's current-balancing assumption (identical phase impedance) holds; asymmetric phase layout causes real-world current imbalance even with a good controller.

## Load switching

- For switching high-current loads on/off (relay coils, motor loads, resistive heaters), use a MOSFET or solid-state relay sized for both continuous current (I²R thermal) and inrush/surge current (e.g., motor locked-rotor current, lamp cold-filament inrush, capacitive load inrush) — check SOA (safe operating area) curves for the switching device under the actual load's turn-on transient, not just steady-state current.
- Flyback/inductive loads (relay coils, motor windings, solenoids) need a freewheeling diode (or snubber/TVS) across the switch to clamp the inductive turn-off voltage spike — omitting this is one of the most common causes of switch failure in relay/motor driver designs.
- For high-side switching of significant current, a high-side driver IC or charge-pump-driven MOSFET is typically needed (gate must be driven above the rail voltage) — see motor_drives_and_motion.md and industrial_plc_io.md for high-side switch topologies in field I/O contexts.

## Worked example: trace width and thermal via count

**Trace width for a 10 A external (top layer) power trace, 2 oz copper, 20°C rise target:**

1. Using an IPC-2152-based calculator (e.g., Saturn PCB Toolkit) with inputs: 10 A, 2 oz (70 µm) copper, external layer, 20°C rise, 25°C ambient — typical output lands around 2.0–2.8 mm (80–110 mil) trace width, noticeably less than the old IPC-2221 chart would demand for the same current/temperature target (IPC-2221 tends to call for wider traces because its underlying data was more conservative and didn't account for modern board/copper effects as precisely).
2. If the same 10 A trace must run on an internal layer instead, expect to need roughly double the width (or move to heavier copper, e.g., 3–4 oz) for the same 20°C rise, because internal layers are sandwiched in fiberglass/prepreg with much poorer heat dissipation to ambient air than an external layer exposed to convection.
3. Always verify with the actual calculator/tool using your specific stackup, not the rule-of-thumb numbers above — they vary with ambient temperature assumption, board thickness, and adjacent copper pours.

**Thermal via count under a 5x5 mm exposed pad dissipating 2 W, target θ(via array) contribution ≤ 15°C/W:**

1. A single filled 0.3 mm thermal via typically contributes on the order of 20–40°C/W depending on board thickness and plating — combining vias in parallel divides this roughly proportionally (with diminishing returns as the destination copper plane itself becomes the bottleneck).
2. To reach ≈15°C/W effective via-array thermal resistance from an assumed single-via figure of ~30°C/W, roughly 2–3 vias in parallel get partway there ideally, but real arrays typically use 9–16 vias under a pad this size once minimum annular ring/spacing design rules and the destination copper plane's own spreading resistance are accounted for — always check the specific IC's datasheet recommended pattern (e.g., a 3x3 or 4x4 grid on a ~1.0–1.2 mm pitch) rather than computing from first principles alone, since manufacturers validate their recommended pattern experimentally.
3. Ensure the destination internal/bottom copper plane is large enough (typically several hundred mm² minimum, more for higher power) to actually spread and dissipate the heat once it reaches the via array — a dense via array feeding a tiny isolated copper island doesn't help much.

## Common mistakes

- Using the old "10 mil per amp" rule of thumb without checking copper weight, layer position (internal vs external), or actual ΔT target — leads to either overbuilt traces (wasted board space) or underbuilt traces on internal layers (overheating).
- Necking a copper pour down to a narrow trace at a connector or component pad, creating an unintended hot spot.
- Skipping thermal via fill/plug on fine-pitch exposed-pad parts, leading to solder voiding and inconsistent thermal/electrical performance across production units.
- Paralleling MOSFETs with asymmetric gate trace lengths/resistor values, causing one device to absorb most of the switching loss.
- Using 2-wire current sensing at low shunt values, introducing large measurement error from trace/connector resistance.
- Paralleling power supplies without any current-sharing mechanism, resulting in one module carrying most of the load and aging/failing prematurely.
- Omitting a freewheeling diode/snubber on an inductive load switch, causing switch overvoltage failure.
- Sizing heatsink/copper area based on average power instead of worst-case (peak sustained) power dissipation.

## Schematic review checklist

- [ ] Trace/plane current capacity computed with an IPC-2152-based method (or equivalent calculator), not a rule-of-thumb table, for any current-carrying net above a few hundred mA.
- [ ] Copper weight specified appropriately for the highest-current nets, with fab minimum trace/space verified for that weight.
- [ ] Thermal budget (Tj = Ta + P×θJA/θJC) computed for every power-dissipating component, with margin below datasheet max.
- [ ] Freewheeling diode/snubber included on every inductive load switch.
- [ ] Kelvin (4-wire) sensing specified for any precision current measurement.
- [ ] Current-sharing scheme (droop, active, or controller-based) specified for any parallel-supply architecture.
- [ ] Paralleled MOSFETs use matched gate resistors and symmetric drive.

## Layout review checklist

- [ ] Trace widths for power nets verified against calculated current capacity at actual copper weight and layer (internal/external).
- [ ] No unintended necking of copper pours at pads/connectors on high-current paths.
- [ ] Thermal via count/pattern under exposed-pad/high-power components follows datasheet guidance; via-in-pad filled/plugged where directly in the solder pad.
- [ ] Copper pour area sized for heatsinking where no discrete heatsink is used, with θJA vs area checked against target.
- [ ] Paralleled FETs laid out symmetrically with matched trace lengths/impedances to source, drain, and gate.
- [ ] Kelvin sense traces routed as tight differential pairs, away from high-current/high-di/dt paths, tapped directly from shunt current pads.
- [ ] Multiphase or paralleled-supply layouts have symmetric trace lengths/impedances from each phase/module to the shared output node.
- [ ] Heatsink mounting (if discrete) has correct TIM specified and adequate clamping/mounting force per the heatsink/TIM datasheet.
