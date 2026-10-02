---
title: High-Speed Signal Integrity Fundamentals
domain: high-speed
tags: [signal-integrity, impedance, differential-pair, crosstalk, length-matching, via-stub, back-drill, KiCad]
applies_to: [digital, high-speed, DDR, PCIe, USB, Ethernet]
---

## Controlled impedance targets

Design every high-speed net to a target impedance and hold it within ±10% (tighter, ±7–8%, for demanding serial links) across its routed length.

- **Single-ended (SE) general logic / GPIO**: 50 Ω is the conventional default reference for microstrip/stripline SE traces.
- **USB 2.0 D+/D-**: 90 Ω differential.
- **USB 3.x SuperSpeed TX/RX pairs**: 90 Ω differential.
- **Ethernet (10/100/1000BASE-T MDI pairs)**: 100 Ω differential.
- **PCIe (all generations)**: 85 Ω differential is PCI-SIG's nominal spec target (some designers use 90 Ω and rely on tolerance; check PCI-SIG CEM spec / your PHY vendor's layout guide — 85 Ω is the commonly cited nominal).
- **LVDS**: 100 Ω differential (nominal, per TIA/EIA-644).
- **HDMI TMDS pairs**: 100 Ω differential.
- **DDR3/DDR4 data/address/command SE lines**: typically 40–60 Ω SE depending on memory vendor's reference design (DDR4 commonly ~40 Ω or per JEDEC/vendor DIMM spec); DDR differential clock/strobe pairs ~80–100 Ω. Always follow the specific DRAM/SoC vendor's memory layout guide — DDR impedance targets are chipset-specific.

## Microstrip vs stripline

- **Microstrip**: trace on an outer layer referenced to one adjacent plane, dielectric partly air (solder mask) and partly PCB substrate. Faster propagation, slightly higher loss due to exposure, easier to probe/rework, but more susceptible to EMI radiation since it's not shielded.
- **Stripline**: trace buried between two reference planes (inner layer). Fully shielded by the planes, lower EMI, tighter and more predictable impedance, but signal must transition through vias to reach an inner layer, and routing is harder to probe.
- Rule of thumb: put DDR, PCIe, and other multi-Gbps differential pairs on stripline layers close to the driving/receiving BGA to minimize via transitions; put lower-speed or single-transition signals (e.g., a single connector-facing pair) on microstrip.

## Length matching and skew budgets

- **Intra-pair skew** (P vs N within a differential pair): keep under roughly 5 mils (0.127 mm) for multi-Gbps serial links (PCIe, USB3, SATA); DDR strobe/data pairs typically want intra-pair skew under 5–10 mil equivalent (check vendor guide — some spec in picoseconds, e.g., <2 ps).
- **Inter-pair/bus skew** (matching across a byte lane's data lines to its strobe, or across lanes to a common clock):
  - **DDR3**: byte lane data/strobe matched to within ~±25 mil (some vendors specify ±50 mil for address/command group relative to clock — always check the specific SoC/DRAM vendor's layout guide, values vary).
  - **DDR4**: tighter, commonly ±10–20 mil per byte lane, driven by fly-by topology timing budget (see `interfaces_usb_ethernet_pcie_ddr.md`).
  - **PCIe**: lane-to-lane skew within a x4/x8/x16 link has a generous budget (many mil, often >1000 mil equivalent) because each lane self-clocks (8b/10b or 128b/130b encoding with embedded clock) — intra-pair skew matters far more than lane-to-lane.
  - **USB3, SATA, Ethernet**: intra-pair skew is the primary concern; inter-pair (TX vs RX) skew is not electrically coupled so it's not matched.
- Always length-match on **trace delay (time)**, not raw physical length, when dielectric or layer changes are present — a stripline mil and a microstrip mil don't propagate signals at the same speed. For same-layer matching, physical length matching is an adequate proxy.

## Reference plane changes and return vias

- Every time a signal changes layer (via), its return current must also find a path across the corresponding plane change. If the signal moves from a layer referenced to GND to one referenced to a different plane (e.g., GND to VCC), and those planes aren't tightly AC-coupled (stitching caps) or continuous, the return current takes a long detour, adding inductance and radiating noise.
- **Rule**: place a **ground stitching via** within about 50–100 mil (closer is better, ideally <30–50 mil for multi-GHz signals) of every signal via that changes reference planes, so return current has a short local path. If the plane transition is GND-to-GND, a stitching via is usually optional at lower speeds but still good practice above a few hundred MHz.
- If the transition is signal-referenced-to-power, add a decoupling/stitching capacitor near the via connecting the two planes (0.01–0.1 µF) as a low-inductance return path, in addition to via stitching where possible.

## Via stubs and back-drilling

- A via drilled through the full board but only used for a short span (e.g., outer-layer signal via that only needs to reach layer 2 of an 8-layer stack) leaves an unused stub below the connection — this stub acts as a resonant transmission-line stub that causes signal reflections, worsening insertion loss at frequencies where the stub length approaches a quarter-wavelength.
- Rule of thumb: stubs become a real concern above ~5 Gbps for typical stub lengths on 1.6 mm boards; for PCIe Gen3+ (8 GT/s), USB3.1+ (10 Gbps), and similar, evaluate stub length.
- **Back-drilling**: after plating, a fab drills out the unused portion of the via barrel from the far side with a slightly larger bit, removing the stub while leaving the used portion intact. Specify back-drill nets explicitly to the fab with a controlled residual stub length (commonly ≤10 mil residual stub requested).
- Alternative: use blind/buried microvias so there's no stub to begin with (common on HDI boards), or place connections on layers close enough together that stub length is negligible.

## AC coupling capacitors

- PCIe, USB3, SATA, DisplayPort, and many SerDes links use **AC coupling caps** (typically 100 nF, 0402 or 0201 package for high speed) in series on the TX pair only (spec-dependent — PCIe requires them on the transmitter side referenced from the add-in card/downstream port per PCI-SIG CEM spec).
- Placement: as close as practical to the transmitting device, matched on both P and N legs (same distance from driver, same footprint/orientation) to avoid reintroducing skew or impedance discontinuity. Keep the pad/via transition compact — an AC cap footprint is itself a small impedance discontinuity, so minimize the trace width change and any stub at the pad.
- Verify polarity/placement rules per protocol spec — some interfaces (e.g., certain LVDS links) don't require AC coupling at all if both ends share common-mode bias.

## Crosstalk and the 3W rule

- **3W rule**: space trace centerlines at least 3× the trace width apart (edge-to-edge spacing ≥ 2× width) to keep coupled crosstalk below roughly 1% for adjacent parallel traces on the same layer. For tightly coupled differential pairs, the "W" applies to the gap between pairs, not within a pair.
- For critical, high-speed single-ended buses (e.g., DDR address/command), increasing to 4–5W spacing further reduces coupling when board area allows.
- Differential pairs: keep intra-pair spacing constant along the route (edge-coupled or broadside-coupled, matching your impedance calculator's assumption) — necking the pair apart to route around an obstacle and back creates an impedance bump and coupling change; avoid it or keep the deviation short.
- Guard traces (grounded trace between two aggressors) help only if stitched to ground frequently (every ~100 mil or less;  otherwise the guard trace itself becomes a floating resonator.

## Serpentine (length-tuning) rules

- Keep serpentine amplitude (the height of each "tooth") at least 3–4× the trace width away from the adjacent trace, and keep spacing between serpentine legs at least 3W to avoid the tuning structure coupling back into itself and undoing its own timing benefit.
- Place length tuning as close as possible to the source of the mismatch (e.g., right after a connector or right before a BGA) rather than spread arbitrarily, and avoid tuning directly under a BGA or connector body where it's hard to inspect and adds unpredictable coupling to nearby escape traces.
- For DDR fly-by topology, tune per the vendor's guide — the tuning is usually **within a byte lane relative to its strobe**, not to an absolute number.

## Differential pair routing in KiCad

- Name nets with a consistent P/N suffix pair — KiCad auto-recognizes common suffixes like `_P`/`_N`, `+`/`-`, `P`/`N` — so the router treats them as a differential pair automatically (Route → Differential Pair mode, shortcut typically `6` in the router, or select "Add Differential Pair" from the toolbar).
- Set the pair's target impedance and gap via a **netclass** or **routing rule** (Board Setup → Design Rules → Net Classes, or a custom `.kicad_dru` rule) — the router uses the class's diff-pair gap and width to maintain the calculated impedance from the stackup editor's impedance tool.
- Use the **Tune Differential Pair Skew** tool (interactive router's length-tuning mode) to add serpentines matching intra-pair skew target; use **Tune Length** (single-ended) for matching a group of single-ended nets (e.g., DDR byte lane) to a target length window defined in the net class or a length-tuning rule.
- KiCad shows real-time length reporting in the router status bar while tuning — confirm against your calculated skew/length budget before finishing the route.

## Eye diagram basics

- An eye diagram overlays many bit periods of a serial signal to visualize timing margin (eye width) and voltage margin (eye height/amplitude).
- **Closing causes**: excessive insertion loss (long traces, lossy dielectric), reflections from impedance discontinuities (vias, connector transitions, stubs), crosstalk from adjacent aggressors, and jitter (clock/data timing noise).
- A "closed" eye (height or width collapses toward zero) means the receiver can't reliably distinguish 0s and 1s — bit errors result. Simulate with an SI tool (e.g., channel simulator provided by SerDes/PHY vendor, or generic tools like Ansys/Keysight) for any link running near or beyond the dielectric/stackup's qualified data rate; don't assume it will "just work" past a few Gbps without at least a basic loss-budget calculation.
- Practical mitigations, roughly in order of impact: shorten trace length, use lower-loss dielectric, reduce via count/stub length (or back-drill), improve differential pair matching, add/verify AC coupling, check connector/footprint impedance continuity, and as a last resort rely on receiver equalization (CTLE/DFE) which most modern SerDes PHYs include — but layout should not depend entirely on RX equalization to rescue a bad channel.

## Insertion loss budgeting

- Total channel insertion loss (dB, at the interface's Nyquist frequency) is the sum of dielectric loss (dominated by Df and trace length), conductor loss (trace resistance, worsened by skin effect at high frequency and by copper surface roughness), and discontinuity loss (connectors, vias, AC caps). Each protocol spec (PCIe, USB, SATA, etc.) publishes a maximum channel insertion loss budget at its operating frequency that the total physical channel — PCB traces, connector, any cable — must not exceed.
- Rough planning numbers (very approximate, vary heavily by dielectric and trace geometry — always get real numbers from a field-solver or the laminate vendor's loss curves for a real budget): generic FR-4 stripline loss is commonly on the order of 1–2.5 dB/inch at multi-GHz frequencies (rising with frequency), while a low-loss laminate (Megtron-6 class) can be under roughly 0.5–1 dB/inch in the same range — this several-times difference is why dielectric selection matters so much once you're routing Gen4+ PCIe, DDR5, or 10G+ Ethernet over more than a few inches.
- Reserve margin: don't spend the entire protocol-spec insertion loss budget on the PCB alone — connectors, cables, and package/BGA transitions all consume part of the same budget, so a practical PCB-only sub-budget should leave headroom (informally, many designers reserve at least 20–30% margin against the total spec limit for the PCB's own contribution, though the exact split is design-specific).

## Skin effect and surface roughness

- **Skin effect**: at high frequency, current crowds into a thin layer near the conductor's surface (skin depth shrinks roughly as 1/√f), increasing effective trace resistance with frequency — this is why conductor loss grows with frequency alongside dielectric loss, and why simply "making the trace wider" only helps up to a point once skin effect dominates.
- **Copper surface roughness**: the electrodeposited copper foil's rough surface (bonded to the dielectric for adhesion) forces high-frequency current to travel a longer effective path along the rough surface texture, adding loss beyond the smooth-conductor skin-effect prediction — this effect becomes significant above a few GHz. Low-loss, high-speed-rated laminates are commonly paired with smoother "low-profile" or "very-low-profile" copper foil specifically to reduce this contribution; specify it explicitly when ordering a board for a multi-Gbps design rather than assuming standard electrodeposited foil roughness is adequate.

## Fiber-weave effect (glass-weave skew)

- PCB dielectric is glass-fiber-reinforced; the glass weave is not homogeneous — a trace running parallel to (and centered on) a bundle of glass fiber sees consistently different effective Dk than a trace crossing perpendicular to or between fiber bundles, because glass fiber and the surrounding resin have different Dk. Two traces of a differential pair, or two matched single-ended traces, can pick up different propagation delay purely from where they happen to fall relative to the glass weave pattern — called the **fiber-weave effect** or **glass-weave skew**.
- Mitigations: rotate the board outline/trace routing by a small angle (commonly 10° or so) relative to the glass weave so both legs of a differential pair cross the same mix of fiber/resin on average rather than one leg tracking a fiber bundle exactly; or specify a spread-glass/flat-glass-style laminate (glass weave engineered to be more uniform, e.g., "1080 spread" style weaves) for the most skew-sensitive high-speed designs. This effect is a genuine, measured contributor to eye-diagram closure on some production boards and is worth knowing about even though it's not something a hobby-scale build typically controls for.

## Simultaneous switching noise (SSN) / ground bounce

- When many output drivers on the same IC switch simultaneously (e.g., a wide parallel bus like DDR data lines all transitioning together), the combined transient current through the shared package/PCB ground (and power) inductance causes a voltage transient on the die's internal ground reference relative to the board ground — called **simultaneous switching noise** or **ground bounce** — which can degrade timing margin or, in severe cases, cause logic errors on other pins of the same IC that aren't even switching.
- Mitigation is primarily at the package/IC level (multiple ground/power pins distributed across the package specifically to divide the return current, on-die/on-package decoupling) but board-level decoupling and low-inductance power/ground plane design (see `stackup_and_layer_count.md` and the accelerator PDN discussion in `bga_fanout_and_gpu_class_boards.md`) directly reduce the board's contribution to the total loop inductance driving this effect.

## Quick reference: target impedances by interface

| Interface | Differential/SE | Target impedance |
|---|---|---|
| General SE logic | Single-ended | 50 Ω |
| USB 2.0 D+/D- | Differential | 90 Ω |
| USB 3.x SuperSpeed | Differential | 90 Ω |
| Ethernet MDI (10/100/1000BASE-T) | Differential | 100 Ω |
| PCIe (all generations) | Differential | 85 Ω nominal |
| LVDS | Differential | 100 Ω |
| HDMI TMDS | Differential | 100 Ω |
| DDR3/DDR4 data/address | Single-ended | ~40–60 Ω (vendor-specific) |
| DDR clock/strobe | Differential | ~80–100 Ω |

## Quick reference: typical skew/matching budgets

| Interface | Intra-pair skew | Inter-pair/bus skew |
|---|---|---|
| PCIe, USB3, SATA | ≤ 5 mil (approx.) | Lane skew budget generous (self-clocked) |
| DDR3 byte lane | ≤ 5–10 mil equiv. | ±25 mil (vendor-specific) |
| DDR4 byte lane | Tighter (ps-level) | ±10–20 mil (vendor-specific) |
| LVDS | Few mil | N/A (independent pairs) |
| MIPI D-PHY | Few mil | N/A |

## Quick reference: when via stubs start to matter

| Data rate | Stub sensitivity | Typical action |
|---|---|---|
| < 1 Gbps | Negligible | No action needed |
| 1–5 Gbps | Low-moderate | Check stub length vs board thickness |
| PCIe Gen3 (8 GT/s) and above | Significant | Back-drill or use blind/buried vias |
| USB3.1+/10 Gbps+ SerDes | Significant | Back-drill or HDI microvia routing |

## Typical differential pair AC-coupling layout (in words)

The transmitting IC's TX+ and TX- pins each connect through a short trace to one pad of their own AC coupling capacitor (0402 or 0201 package, matched footprint orientation on both legs); the capacitors' far pads continue as the main differential pair route toward the receiver or connector. Both capacitors are placed at the same distance from the driver (mirrored across the pair's centerline) so neither leg gains extra length relative to the other, and both sit on the same PCB layer with no via between the driver and the capacitor pair if at all avoidable, keeping that short, most-sensitive segment of the route via-free and impedance-continuous.

## Typical reference-plane-change via with stitching (in words)

A high-speed signal trace on the top layer reaches a via that carries it down to an inner stripline layer. That via's barrel passes through the ground plane layer sitting between the top layer and the destination stripline layer. Immediately adjacent to the signal via (within roughly 30–100 mil), a separate ground via connects the top-layer ground pour directly to the same ground plane the signal via passes through, giving the return current a short, local path to follow the signal's layer transition rather than having to detour to the nearest existing ground via elsewhere on the board. If the signal instead transitions between two layers referenced to different planes (e.g., top-layer signal referenced to ground, inner-layer signal referenced to power), a decoupling capacitor is placed near the via connecting the ground and power planes together at that location, serving as the AC return path bridge instead of a simple ground-via stitch.

## Common mistakes

- Routing a differential pair with inconsistent spacing (necking near connectors, wide elsewhere) without re-checking impedance.
- Ignoring return-path discontinuities at plane splits — a trace crossing a split plane is one of the most common EMI/SI root causes found in the field.
- Treating length matching as "make total physical length equal" when dielectric changes make that inaccurate — should match propagation delay.
- Leaving unused via stubs on Gen3+ PCIe or 10G+ Ethernet routes without evaluating or back-drilling them.
- Placing AC coupling caps asymmetrically (different trace lengths to each pad) reintroducing skew that the rest of the route carefully avoided.
- Assuming a 4-layer board with no adjacent plane on a signal layer can still hit 50 Ω — impedance without a controlled reference plane is not predictable.

## Schematic review checklist

- Every controlled-impedance net has a documented target impedance value next to it (comment/net class name) so layout doesn't have to guess.
- AC coupling caps are shown explicitly on every net that the protocol spec requires them for (PCIe TX, etc.), with correct value and package noted.
- Differential pairs are named with consistent P/N suffixes matching KiCad's auto-recognized patterns.
- Termination requirements (series source termination, differential termination resistors) are captured in the schematic per interface spec, not left implicit.
- Any planned back-drilled vias are called out so the layout/fab package includes them.

## Layout review checklist

- Net classes / custom rules define correct trace width and gap for each impedance target, verified against the stackup's impedance calculator output, not guessed.
- Every reference-plane change on a high-speed via has a nearby stitching via or decoupling cap.
- 3W (or better) spacing maintained between non-paired high-speed traces; diff pairs keep constant intra-pair spacing along their length.
- Intra-pair and relevant inter-pair/bus length matching verified against the interface's skew budget using the router's length report.
- Via stub lengths evaluated for any link ≥5 Gbps; back-drilling specified in fab notes where needed.
- No high-speed trace crosses a plane split or anti-etch gap in its reference layer.
- Serpentine tuning structures meet 3–4W amplitude/spacing rule and are placed near the mismatch source, not arbitrarily.
