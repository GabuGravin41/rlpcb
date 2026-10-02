---
title: Load Balancing and Power Distribution Board Reference Architecture
domain: power
tags: [current sharing, oring, hot-swap, efuse, pmbus, busbar, redundant power, parallel supplies]
applies_to: [power distribution boards, load-share controller boards, redundant psu backplanes, busbar systems]
---

## System overview

A power distribution/load-balancing board sits between two or more redundant power supplies (or supply modules) and a shared DC bus feeding downstream loads, ensuring supplies share current predictably, a failed supply doesn't drag the bus down or back-feed fault current into it, and downstream branches can be individually protected, monitored, and hot-swapped. Common in data-center power shelves, telecom -48 V plants, industrial redundant-supply cabinets, and multi-PSU server/rack systems.

## Key part families

- **ORing controllers**: ideal-diode/ORing MOSFET controller ICs (e.g., TI LM74700-class, Analog Devices LTC4359-class) for active reverse-current blocking with near-zero forward drop.
- **Hot-swap controllers**: hot-swap/inrush controller ICs (e.g., TI LM5069-class, Analog Devices LTC4218-class) providing controlled dV/dt insertion and programmable current limiting.
- **eFuses**: electronic fuse ICs (e.g., TI TPS25940-class, Infineon eFuse families) with programmable current limit, fast trip, and PMBus/I2C telemetry.
- **Load-share controllers**: dedicated current-share controller ICs or supply-integrated share-bus support for active analog current sharing among parallel supplies.
- **PMBus/telemetry**: PMBus-compliant power monitor ICs (e.g., TI INA23x-class, Analog Devices power monitors) for branch-level voltage/current/temperature reporting.
- **Busbars/connectors**: bolted copper busbar stock, high-current press-fit power connectors, and heavy-gauge power connectors rated for the bus's continuous and fault current.

## Current sharing of parallel supplies

- **Why active sharing is needed**: two nominally-identical DC-DC or AC-DC supplies wired directly in parallel will not share load current equally by default — small output-voltage-setpoint mismatches (even a few tens of mV) cause the higher-set supply to carry disproportionately more current, potentially exceeding its rating while the other supply idles. Active current sharing corrects this.
- **Droop sharing (passive/simple)**: each supply's output voltage is intentionally set to droop slightly with load current (a small effective output resistance, either inherent or added via a sense resistor and feedback), so a supply carrying more than its share of current sees a slightly lower output voltage, naturally shifting load toward the less-loaded supply until they equalize. Simple, requires no inter-supply communication, but gives somewhat looser sharing accuracy and a small bus voltage regulation penalty proportional to load.
- **Active current-share bus**: supplies (or their load-share controller ICs) communicate over a dedicated analog share-bus line, each adjusting its own output slightly to match the bus's average current signal — standard in redundant server PSUs and many industrial parallel-supply systems, giving tighter sharing accuracy (often within a few percent) without materially sacrificing bus regulation. The share-bus line itself needs protection/isolation consideration if supplies are hot-swappable, since a bad connector mate shouldn't corrupt sharing for supplies still seated.
- **Digital/PMBus-coordinated sharing**: in systems with a supervisory controller, each supply reports its output current over PMBus/I2C and the controller (or a master supply) adjusts setpoints digitally — offers the most flexibility (e.g., deliberately unequal sharing ratios, prioritized shutdown order) at the cost of dependency on the digital control loop's own reliability; a well-designed system falls back to autonomous droop/analog sharing if the digital link is lost, rather than becoming unstable without it.

## ORing: combining redundant supply outputs

- **Purpose**: ORing lets multiple supply outputs connect to a single shared bus such that each supply can source current to the bus, but current cannot flow backward from the bus into a failed/lower-voltage supply — essential for N+1 or 2N redundancy so one supply's failure (including a failure mode where its output collapses toward zero or shorts internally) doesn't pull down the shared bus or draw fault current from the healthy supplies.
- **Diode ORing**: the simplest approach — a Schottky or standard rectifier diode in series with each supply's output. Simple and inherently fail-safe (a diode is a passive component with a well-understood failure mode), but the forward voltage drop (0.3–0.7 V typical) wastes power and requires headroom in the supply's output voltage setpoint, worsening at high current where I²R-scale diode dissipation also becomes a real thermal design item.
- **Ideal diode / ORing FET controllers**: an ORing controller IC drives a MOSFET in place of the diode, actively controlling the FET to conduct with near-zero forward drop when its supply is the higher/active source and to turn off quickly (within microseconds) when reverse current is detected — this is now the standard approach in efficiency-sensitive or high-current redundant systems (data center PSUs, telecom -48 V plants) since it eliminates most of the diode's power loss while preserving the same reverse-current-blocking safety function. Choose a controller IC with fast enough turn-off response for the worst-case fault (a hard output short on one supply) so the reverse current spike before turn-off stays within the FET's and the bus capacitor's ratings.
- **Redundancy verification**: an ORing architecture's whole point is defeated if a single-point failure (e.g., a shorted ORing FET, which some ORing controllers explicitly detect and protect against) can still couple a faulted supply to the bus — check the specific controller IC's fault-handling behavior for a shorted-FET failure mode, not just the normal reverse-current-blocking case.

## Hot-swap and inrush control

- **Hot-swap controller IC**: manages the connection of a supply module or downstream load board to a live bus, ramping the connecting MOSFET's gate slowly (controlled dV/dt) to limit inrush current charging the new board's local bulk capacitance — without this, plugging a board with, say, several hundred µF of local capacitance into a live 12 V or 48 V bus can draw an inrush current spike large enough to droop the bus voltage for every other board already connected, or trip upstream protection.
- **Circuit breaker / current-limit function**: most hot-swap controllers also provide a programmable current limit and a fast (µs-scale) circuit-breaker trip if downstream current exceeds a threshold for longer than a set blanking time — protecting the shared bus from a downstream short on any one branch.
- **Sequencing with ORing**: hot-swap and ORing functions are frequently combined in a single controller IC or a closely coordinated pair, since a hot-swap event (inserting a new supply) and an ORing event (that supply beginning to source current onto an already-live bus) happen together — verify the combined behavior specifically (many vendor reference designs pair these two functions and are a good starting point rather than combining separately-sourced ICs without integration testing).

## eFuses for downstream branch protection

- An eFuse (electronic fuse) IC replaces a traditional fuse for each downstream load branch, providing programmable current limiting, fast overcurrent/short-circuit response, undervoltage/overvoltage lockout, and (in many parts) I2C/PMBus telemetry reporting branch current/voltage/fault status — see power_high_current_and_thermal.md for general high-current protection component selection principles.
- Advantages over a traditional fuse: resettable (no field fuse-replacement needed after a transient fault), faster and more precisely characterized trip behavior, adjustable current limit without a hardware change (in digitally-programmable parts), and built-in diagnostics — tradeoffs are higher per-channel cost and the eFuse IC's own power dissipation (RDS(on) loss) at high continuous current, which needs its own thermal design.
- Retry behavior: configure (per the eFuse IC's options) whether a tripped branch auto-retries periodically or latches off until commanded/power-cycled — auto-retry is convenient for transient-fault tolerance but can mask a persistent fault that should actually be latched and reported, so choose deliberately per branch's criticality, not as a default.
- Branch-level telemetry (via PMBus/I2C) feeding a supervisory controller enables load shedding decisions (deliberately disabling lower-priority branches under a system-wide power budget constraint) — a common pattern in high-density server/rack power distribution.

## PMBus monitoring architecture

- **PMBus** (a superset of SMBus/I2C with standardized power-management commands) is the dominant digital interface for querying supply/eFuse/hot-swap-controller telemetry (voltage, current, temperature, fault status, power) and, where supported, commanding setpoints or enable states — see power_buck_boost_converters.md and power_decoupling_and_pdn.md for PMBus-controlled point-of-load converter context.
- Address assignment: PMBus devices need distinct bus addresses on a shared bus segment — resistor-strapped address pins (common) or address-translator/multiplexer ICs (for systems with many identical hot-swappable modules that would otherwise collide on default addresses) are the two standard solutions; plan address assignment at the architecture stage since it constrains how many identical modules can share one bus segment.
- Isolation: where the PMBus segment crosses an isolation boundary (e.g., monitoring an isolated AC-DC supply's primary-side or a battery-referenced module from an isolated system controller), use an isolated I2C/PMBus buffer/repeater IC rather than assuming the digital signal's low voltage makes isolation unnecessary — the same isolation-rating-consistency principle from industrial_plc_io.md applies.
- A supervisory MCU aggregating PMBus telemetry across all supplies/branches is the natural place to implement system-level protection logic (load shedding, staged shutdown on brownout, fault logging) — but any protection function whose failure would be catastrophic (e.g., preventing a branch overcurrent from damaging downstream equipment) should still have its own local, independent protection (the eFuse/hot-swap controller's own hardware limit) rather than depending solely on the supervisory MCU reacting in time.

## Busbars and high-current interconnect

- For bus currents beyond roughly 30–50 A (a rough threshold; verify against actual trace-width/copper-thickness capacity per IPC-2152 or equivalent thermal-rise calculations), solid copper busbars (bolted or press-fit to the PCB, or an integrated thick-copper PCB layer) become more practical than relying on PCB copper alone — see power_high_current_and_thermal.md for current-capacity calculation methodology.
- Busbar sizing: cross-sectional area sized for continuous current at an acceptable temperature rise (commonly targeting well under 30°C rise above ambient for a conservative industrial design), plus mechanical/vibration considerations for the connection method (bolted lug connections need adequate torque spec and, often, Belleville washers to maintain contact pressure through thermal cycling).
- Busbar-to-PCB connection: press-fit pins, bolted lugs through plated through-holes with adequate copper annular ring, or bonded/soldered tab connections — each has different current-capacity and mechanical-robustness tradeoffs; bolted connections are generally preferred for the highest currents and for field-serviceability.
- Voltage drop budget: even low-resistance busbars/copper have finite resistance — for a long distribution run, calculate voltage drop at maximum current and verify it stays within the downstream loads' input voltage tolerance, not just checking thermal rise alone.

## Layer count and stackup

- Power distribution boards typically use 4–8 layers with one or more dedicated heavy-copper (2 oz+) power/ground plane pairs for the main bus, separate from thinner signal layers carrying PMBus/control signals — see stackup_and_layer_count.md.
- High-current boards sometimes use mixed copper weights per layer (e.g., heavy copper only on the power planes, standard weight on signal layers) — confirm with the fab that mixed-weight stackups are within their standard capability before finalizing, since not every shop offers this without a custom quote.

## Placement and routing priorities

1. ORing FETs/diodes and hot-swap controllers placed immediately at each supply's connection point to the shared bus, minimizing the loop between the supply connector and the ORing device.
2. eFuse/branch-protection ICs placed close to their downstream connector, with adequate copper pour for the IC's own thermal dissipation at rated current.
3. Bulk bus capacitance distributed across the board (not concentrated in one spot) to keep local impedance low near each load connection point, especially for hot-swap inrush behavior.
4. Busbar mounting/connection points positioned per the mechanical/enclosure design, with adequate copper plane connection and via count under each pad to handle the full current without relying on a single via.
5. PMBus/I2C control traces routed away from high-current switching (ORing FET switching transients, hot-swap inrush events) to avoid coupling noise into the monitoring bus.

## Safety and standards

- UL 60950-1/62368-1 or equivalent for general electronic equipment safety, IEC 60664-1 for creepage/clearance at the bus's working voltage.
- Telecom -48 V systems often reference NEBS (Telcordia GR-1089/GR-63) for additional environmental/safety requirements beyond general electronic equipment standards.
- Any board carrying bus currents in the tens-to-hundreds-of-amps range should have its high-current paths reviewed against fire-safety-relevant thermal limits (conductor temperature rise, connector current rating margin), not just functional performance.

## Test and bring-up plan

1. Bring up one supply feeding the bus alone first, verifying ORing/hot-swap behavior in isolation before adding a second parallel supply.
2. Add the second (redundant) supply and verify current sharing accuracy across the load range (light load through full load) against the sharing scheme's expected tolerance.
3. Hot-swap test: insert/remove a supply module while the bus is live and loaded, verifying inrush stays within spec and the bus voltage doesn't droop enough to disturb other connected loads.
4. Fault injection: short one supply's output (or simulate via the bench supply's own protection) and verify the ORing function prevents reverse current/bus collapse, and that the healthy supply(s) seamlessly carry the full load.
5. eFuse branch test: short a downstream branch and verify trip time/current against the eFuse's programmed limit, and verify retry/latch behavior matches the intended configuration for that branch.
6. PMBus telemetry validation: verify reported voltage/current/temperature values against independent bench measurement across the load range, not just at a single calibration point.
7. Thermal test at full rated bus current, checking busbar/connector temperature rise and eFuse/ORing FET case temperature against datasheet limits.

## Common failure modes

- Parallel supplies without active current sharing, causing one supply to chronically carry disproportionate load and age/fail prematurely.
- ORing controller that doesn't detect a shorted-FET failure mode, defeating redundancy when that specific failure occurs.
- Hot-swap inrush control omitted or misconfigured, causing bus voltage droop or upstream protection trips whenever a module is inserted.
- eFuse branches all configured with the same default retry behavior regardless of downstream criticality, masking a persistent fault on a branch that should have latched off and alerted.
- PMBus address collisions when multiple identical hot-swappable modules are installed without a working address-assignment scheme.
- Busbar/connector sized for average current without checking worst-case peak/transient current, leading to overheating under real operating conditions not captured by a steady-state-only calculation.

## Schematic review checklist

- [ ] Current-sharing scheme (droop, active analog bus, or digital PMBus) specified and consistent across all parallel supplies in the design.
- [ ] ORing device (diode or ideal-diode FET controller) selected with adequate reverse-current turn-off speed for worst-case fault, and shorted-FET protection considered if using an ideal-diode controller.
- [ ] Hot-swap inrush control present at every hot-pluggable connection point.
- [ ] eFuse current limit, trip response, and retry/latch behavior configured deliberately per branch, not left at generic defaults.
- [ ] PMBus address assignment scheme defined for all addressable devices on each bus segment, with isolation where the segment crosses an isolation boundary.
- [ ] Busbar/high-current interconnect sized for worst-case (not average) current with a documented voltage-drop and temperature-rise calculation.

## Layout review checklist

- [ ] ORing and hot-swap devices placed with minimal loop area at each supply's bus connection point.
- [ ] eFuse ICs have adequate copper pour/thermal relief for rated continuous current.
- [ ] Bulk bus capacitance distributed near load connection points, not concentrated in a single location.
- [ ] Busbar mounting pads have adequate via count and plane connection to carry full rated current without relying on a single via.
- [ ] PMBus/I2C control traces routed away from ORing/hot-swap switching transients and high-current copper.
- [ ] High-current copper (planes, busbars) sized and verified against IPC-2152 or equivalent thermal-rise calculation, not just visual trace width.
