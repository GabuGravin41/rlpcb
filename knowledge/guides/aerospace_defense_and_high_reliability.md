---
title: Aerospace, Defense, and High-Reliability PCB Design Principles
domain: aerospace
tags: [IPC-Class-3, DO-254, DO-160, MIL-STD-461, MIL-STD-810, MIL-STD-704, derating, conformal-coating, rigid-flex, traceability, counterfeit]
applies_to: [aerospace, avionics, defense, high-reliability]
---

This file covers publicly available engineering principles used in high-reliability design. It does not contain, and should never be extended to contain, export-controlled technical data, weapon-specific designs, or anything beyond generally published standards' scope and intent.

## IPC Class 3

IPC-6012 (rigid PCB qualification/performance) and IPC-A-610 (acceptability of electronic assemblies) both define three classes:

- **Class 1**: general electronic products where cosmetic imperfections are acceptable and the major requirement is function.
- **Class 2**: dedicated service electronic products requiring high reliability and extended life — the default for most industrial/commercial products.
- **Class 3**: high-reliability electronic products where continued performance or performance-on-demand is critical, equipment downtime cannot be tolerated, and the end-use environment may be uncommonly harsh — this is the class used for avionics, military, medical-implantable, and similar applications.

Class 3 tightens numerous acceptance criteria versus Class 2: larger minimum annular ring, more conservative plating thickness requirements, stricter solder joint fillet/void criteria (per IPC-A-610), tighter allowed defects on conductor spacing/etch, and more rigorous documentation of process control. When targeting Class 3, specify it explicitly in fabrication and assembly notes (silkscreen/fab drawing callout: "Fabricate per IPC-6012 Class 3" and "Assemble per IPC-A-610 Class 3") — a fab/assembler building to Class 2 default will not automatically apply Class 3 criteria.

## DO-254 and DO-160 (generic overview)

- **DO-254 ("Design Assurance Guidance for Airborne Electronic Hardware")**: defines a design assurance process (not a set of electrical design rules) for complex airborne electronic hardware (FPGAs, ASICs, custom PCB hardware) correlated to a Design Assurance Level (DAL A through E, A being catastrophic-failure-critical) based on the failure condition severity the hardware could contribute to. It requires structured requirements capture, traceability from requirements through design, verification (including formal verification approaches for programmable logic at higher DAL), configuration management, and process assurance — essentially a rigorous, auditable engineering process, not a specific technical rule. Applying DO-254 to a project means planning the whole development lifecycle (requirements → design → verification → certification liaison) around its process objectives, which is a program-level decision, not a layout checklist item.
- **DO-160 ("Environmental Conditions and Test Procedures for Airborne Equipment")**: defines a battery of environmental qualification tests (temperature/altitude, vibration, humidity, waveform/power-input transients, EMI/RF susceptibility and emissions, lightning-induced transient susceptibility, and more), each with numbered sections/categories that a given piece of equipment is qualified against depending on its installation location and criticality. Designing "for DO-160" in practice means designing margins (thermal, mechanical, power-input transient immunity) that anticipate the specific sections' test levels the equipment will be qualified to, and it is validated by actual qualification testing, not by PCB layout alone.

## MIL-STD-461 (EMI)

Defines conducted and radiated emissions and susceptibility test methods/limits for military equipment (e.g., CE102 conducted emissions, RE102 radiated emissions, CS101/CS114 conducted susceptibility, RS103 radiated susceptibility, among many others). Practical board-level design implications:
- Solid, unbroken reference/ground planes and short return paths (same fundamentals as `high_speed_signal_integrity.md`) reduce radiated emissions at the source.
- Filtering (common-mode chokes, feedthrough capacitors, pi filters) on every cable/connector interface that leaves the enclosure, since conducted emissions/susceptibility limits are measured at the equipment's external interfaces.
- Enclosure shielding effectiveness and connector/cable shield termination (360° shield termination at the connector backshell, not a pigtail) matter as much as the PCB itself for meeting radiated limits.
- Power-line filtering sized against the specific CE102/CS101-type limit and frequency range the program requires.

## MIL-STD-810 (environmental/mechanical)

Defines test methods for environmental conditions (vibration, shock, temperature, humidity, altitude, sand/dust, salt fog, etc.) a piece of equipment must survive. Board-level implications: component selection with adequate vibration/shock rating (e.g., avoid tall, heavy through-hole components without additional mechanical support/staking; prefer components with adequate solder joint area relative to mass), conformal coating for humidity/contamination resistance (below), adequate board thickness/stiffening for the expected vibration environment, and connector/cable strain relief.

## MIL-STD-704 (aircraft electrical power characteristics)

Defines the characteristics of electrical power available on military aircraft (voltage ranges, transients, frequency for AC systems, abnormal/emergency conditions) that airborne equipment's power input must tolerate. Practical implication: power supply input stage must be designed with margin for the transient/surge levels this standard defines (or the equivalent commercial DO-160 power-input sections), typically requiring transient suppression (TVS, input filtering) and a wider input voltage tolerance than a typical commercial product would need.

## Derating

High-reliability design applies **derating**: operating a component well below its maximum rated parameter (voltage, current, power, temperature) to extend life and reduce failure rate, since component failure rates typically increase sharply as stress approaches the rated maximum. General public-domain derating philosophy (as reflected in resources like NASA's EEE-INST-002 and MIL-HDBK-338 statistical reliability concepts) commonly applies guidelines such as:
- **Capacitors**: derate voltage rating by roughly 50% (i.e., operate at ≤50% of rated voltage) for ceramic capacitors in high-reliability applications, partly because ceramic capacitance also derates with applied DC voltage (a well-known effect worth checking on any capacitor's DC-bias curve regardless of reliability class).
- **Resistors**: derate power dissipation to roughly 50% of rated power.
- **Semiconductors**: derate voltage (e.g., ≤80% of breakdown/rated voltage) and junction temperature margin (keep well below maximum rated junction temperature under worst-case ambient + self-heating).
- **Electrolytic capacitors**: derate voltage more aggressively (commonly 50% or more) since they're a common wear-out/failure item; consider lifetime-vs-temperature curves from the datasheet (electrolytic life roughly halves for every ~10°C rise per the classic Arrhenius-based rule many vendors publish) when selecting for long-life applications.
- Always derive actual derating factors from the program's applicable specification or the component vendor's application note rather than treating the numbers above as universal rules — they vary by program and component class.

## Redundancy

High-reliability systems commonly use redundancy to meet availability/safety requirements beyond what a single string of hardware can achieve:
- **Dual/triple modular redundancy**: duplicate critical circuits (power supplies, sensors, processing) with voting or failover logic so a single failure doesn't take down the function.
- **N+1 power supplies**: extra power supply capacity beyond the minimum needed, so one unit's failure doesn't interrupt power.
- Redundancy adds board complexity (more layers, more isolation between redundant channels, careful attention to common-cause failure points like a shared connector or shared ground return that could defeat the redundancy's purpose) — a redundant design is only as good as the independence of its failure modes.

## Conformal coating

A thin protective polymer layer (acrylic, urethane, silicone, or parylene, among others) applied over the assembled board to protect against moisture, dust, chemical contamination, and to some degree, vibration-induced solder joint stress and tin whisker mitigation.
- Selectively mask connectors, test points, heatsink contact surfaces, and any component needing to remain uncoated (e.g., some relays/switches, adjustable components) before coating.
- Parylene (vapor-deposited) gives the most uniform, complete coverage (including into small gaps) but requires specialized equipment and full removal for rework; acrylic/urethane are brush/spray-applied and more rework-friendly but less uniform in tight spaces.
- Conformal coating does not replace proper board cleaning (removing flux residue) — coating over contamination traps it and can accelerate corrosion rather than prevent it.

## Rigid-flex

Combines rigid PCB sections with flexible polyimide sections in one continuous, laminated assembly, eliminating cable/connector interconnects between rigid boards in a 3D assembly — reduces connector count (each connector is itself a reliability risk point: contact wear, vibration-induced intermittents), reduces weight, and allows the assembly to conform to a 3D mechanical envelope (common in avionics boxes and missile-guidance-class packaging where space/weight are tightly constrained, described here only as general industry practice).
- Design considerations: minimum bend radius for the flex section (commonly quoted as roughly 10× the flex laminate thickness for dynamic flexing, or less restrictive for a static one-time bend during assembly — always confirm with the specific flex material/fab's capability), controlled-impedance routing across the rigid-flex transition, and stiffener placement at connector/component locations within the flex region to prevent flex fatigue at solder joints.
- Rigid-flex fabrication is a specialized (and higher cost, longer lead time) service compared to standard rigid PCB fabrication — verify a prospective fab actually offers it and at what layer count/complexity before committing a design to it.

## Component obsolescence and counterfeit avoidance

- **Obsolescence management**: high-reliability programs often run for years to decades; select components with published long-term availability commitments where possible, track manufacturer end-of-life (EOL)/product-change notifications (PCNs), and consider lifetime-buy or second-source qualification strategies for components critical to long-program-life products.
- **Counterfeit avoidance**: procure components only through the manufacturer or their authorized/franchised distributors (verifiable on the manufacturer's own website) for any high-reliability or safety-critical build — the broker/gray market carries materially higher counterfeit risk (recycled, relabeled, or out-of-spec parts passed off as new). Publicly available guidance in this space is documented in standards such as AS6081 (counterfeit electronic parts avoidance, distributors) and AS5553 (counterfeit electronic parts, avoidance/detection/mitigation, for organizations); referencing and following such a program's counterfeit-avoidance policy is standard practice, not optional, on any program where component provenance matters. Retain certificates of conformance / traceability documentation from authorized sources.

## Traceability

- Maintain lot/date-code traceability for critical components (recording which lot/date-code went into which serial-numbered assembly) so a field failure or a supplier quality escape can be traced to the affected population without a blanket recall of every unit ever built.
- Serialize assemblies and maintain a build record (BOM revision, assembly work instructions revision, test results) per unit for programs where field failure investigation or configuration audit is required.
- This is a program/process discipline (document control, ERP/MES-level record keeping) more than a PCB design activity, but the PCB design should support it — e.g., include a serial number / date code silkscreen field and a unique board ID (barcode/QR footprint or programmable ID chip) if the program requires unit-level traceability.

## Parts selection and screening levels

- High-reliability programs commonly specify parts by **screening/quality level** beyond a commercial-grade part — e.g., military (MIL-PRF) qualified parts (referenced generically here as a public standards category, such as MIL-PRF-38535 for microcircuits or MIL-PRF-55110/MIL-PRF-31032-class specifications for resistors/capacitors) that impose additional burn-in, electrical test, and lot-traceability requirements beyond standard commercial parts, at correspondingly higher cost and often longer lead time.
- **Upscreening** (buying a commercial-grade part and subjecting it to additional test/burn-in in-house or through a third-party screening house) is sometimes used as a lower-cost alternative to a fully mil-spec part when a qualified equivalent isn't available, though it does not carry the same pedigree as a part manufactured under a full mil-spec quality system from the start — programs generally document which approach was used and why for each critical part.
- Package type matters for reliability: hermetic packages (ceramic, metal-can) resist moisture ingress far better than standard plastic-encapsulated packages and are often specified for the most extreme environments; plastic-encapsulated microcircuits (PEMs) are increasingly accepted for many high-reliability applications short of the most extreme environments, following programs like NASA's PEM usage guidelines, but the decision is program-specific.

## Thermal management for high-reliability boards

- Component junction temperature margin (see derating above) depends directly on the board's thermal design — adequate copper area/thermal vias under power components, and in many high-rel programs, explicit worst-case thermal analysis (steady-state and transient) rather than assuming "it runs cool enough on the bench."
- Conduction-cooled designs (common in sealed avionics enclosures with no forced air) rely on a thermally conductive path from component to case/chassis, often via a metal-core PCB, thermal straps, or a card-edge wedge-lock/cold-wall interface transferring heat to the enclosure wall — component placement and copper pour design should support this heat path deliberately, not as an afterthought.
- Tin whisker mitigation (relevant where pure-tin or high-tin finishes are used, since tin whiskers are a known cause of intermittent shorts and long-term field failures in some high-reliability applications) is addressed through finish selection (e.g., preferring tin-lead or nickel-palladium-gold finishes where RoHS exemptions for high-reliability/aerospace/defense use apply) and, where pure-tin finishes cannot be avoided, conformal coating and/or physical barriers as a mitigation per the program's applicable whisker-mitigation guidance.

## Environmental stress screening (ESS) and burn-in

- Beyond design-stage derating, high-reliability production commonly includes **environmental stress screening**: thermal cycling and/or vibration applied to every production unit (not just a qualification sample) specifically to precipitate early-life ("infant mortality") failures before the unit ships, consistent with the classic reliability "bathtub curve" concept — this is a manufacturing/test process decision informed by the design (does the board have adequate test points and accessible diagnostics to support ESS fault isolation) as much as a pure test-floor decision.
- Burn-in (extended powered operation, often at elevated temperature) serves a similar early-life-failure-precipitation purpose for specific high-risk components or subassemblies.

## Documentation and configuration management

- High-reliability programs maintain rigorous configuration management: every schematic/layout revision, BOM revision, and firmware revision is uniquely identified and controlled, with a documented change process (engineering change requests/orders) rather than informal edits — this underpins both traceability (above) and the ability to correlate a field failure with the exact design/build configuration that produced the failed unit.
- Design documentation for these programs typically includes a worst-case circuit analysis (WCCA) demonstrating the circuit functions correctly across the full specified temperature, voltage, and component-tolerance range simultaneously (not just at nominal conditions) — a materially more rigorous exercise than typical commercial design review.

## Quick reference: IPC Class 2 vs Class 3 (illustrative deltas)

| Parameter | Class 2 (typical) | Class 3 (typical) |
|---|---|---|
| Minimum annular ring | Standard IPC-6012 Class 2 minimum | Larger, more conservative minimum |
| Allowed etch/conductor defects | Some cosmetic allowance | Tighter, less cosmetic allowance |
| Solder joint fillet/void criteria (IPC-A-610) | Class 2 acceptance | Stricter Class 3 acceptance |
| Plating thickness requirements | Standard | More conservative minimum |
| Process documentation/inspection rigor | Standard | Enhanced, more auditable |

## Quick reference: common derating targets (illustrative, confirm per program spec)

| Component type | Parameter derated | Typical high-rel target |
|---|---|---|
| Ceramic capacitor | Voltage | ≤ 50% of rated voltage |
| Electrolytic/tantalum capacitor | Voltage | ≤ 50% (often more conservative) |
| Resistor | Power dissipation | ≤ 50% of rated power |
| Semiconductor | Voltage (breakdown) | ≤ 80% of rated |
| Semiconductor | Junction temperature | Significant margin below Tj max |
| Connector | Current per contact | ≤ 50–75% of rated, per program spec |

## Quick reference: standards mentioned in this guide

| Standard | Scope |
|---|---|
| IPC-6012 | Rigid PCB qualification and performance, Class 1/2/3 |
| IPC-A-610 | Acceptability of electronic assemblies, Class 1/2/3 |
| DO-254 | Design assurance process for airborne electronic hardware |
| DO-160 | Environmental qualification test procedures for airborne equipment |
| MIL-STD-461 | Conducted/radiated EMI emissions and susceptibility |
| MIL-STD-810 | Environmental engineering considerations and test methods |
| MIL-STD-704 | Aircraft electrical power characteristics |
| AS6081 / AS5553 | Counterfeit electronic parts avoidance/detection |
| NASA EEE-INST-002 | Publicly available EEE parts selection/derating guidance |
| MIL-HDBK-338 | Publicly available electronic reliability design handbook |

## Typical redundant power supply architecture (in words)

Two (or more) independent power supply modules each take input from a shared or separately fused input bus and each produce the same output voltage into a common output bus through an isolation element (an ideal-diode controller with a MOSFET, or a simple diode-OR arrangement in a lower-performance implementation) preventing one failed/powered-down module from backfeeding or loading the other's output. Each module has its own independent input filtering, independent control loop, and ideally an independent reference/clock source rather than sharing one, so a single fault (e.g., a shared reference IC failing) cannot disable both modules simultaneously — this independence is the entire point of the redundancy and should be explicitly checked during design review rather than assumed. Health/status monitoring from each module (power-good, current, temperature) feeds a supervisory function that can report a degraded-redundancy condition (one module down but system still operating on the other) to the wider system for maintenance action, rather than only alerting on a full system failure.

## Typical conformal-coating masking approach (in words)

Before coating, connectors, test points, any relay/switch contact requiring mechanical actuation, heatsink mating surfaces, and any adjustable component (trimmer, potentiometer) are covered with a removable mask (a purpose-cut adhesive film, RTV silicone dam, or a mechanical fixture depending on production volume) so the coating material does not reach these surfaces during spray or dip application. After coating and curing, the masks are removed, exposing clean, coating-free contact/mating surfaces while the rest of the board — including all solder joints and exposed copper not otherwise protected — carries a continuous, unbroken coating film. Coating thickness is verified (commonly by visual UV-fluorescent inspection, since many coating formulations include a UV tracer) to confirm complete, consistent coverage with no thin spots or bare patches, particularly around component leads and under low-clearance parts where coating material can struggle to flow evenly.

## Common mistakes

- Specifying "Class 3" in a design note but not confirming the fab/assembler actually builds and inspects to that class's criteria (Class 3 requires more than just tighter DRC — process control and inspection rigor matter too).
- Treating DO-254/DO-160 as line items to "add" late in a design rather than as a lifecycle process/qualification program that needs to shape requirements capture and verification planning from the start.
- Applying commercial-grade capacitor voltage derating (or none) to a Class-3 design without recalculating per the program's actual derating specification.
- Coating over unclean flux residue, trapping contamination instead of protecting against it.
- Sourcing components from unauthorized brokers for a safety-critical build to save cost or lead time, introducing counterfeit risk.
- Designing a "redundant" circuit that shares a single point of failure (one connector, one ground return, one clock source) that defeats the purpose of the redundancy.
- Ignoring flex-region minimum bend radius and stiffener placement, leading to flex fatigue cracking at solder joints near the rigid-flex transition.

## Schematic review checklist

- Target IPC class (2 or 3) stated explicitly and consistently across schematic notes, fab drawing, and assembly drawing.
- Derating targets for critical components (voltage, power, temperature) documented and checked against actual applied stress in the design, not assumed.
- Redundant circuits reviewed for shared single points of failure (shared connector, shared ground/return path, shared clock/reference).
- Power input stage design margined against the program's applicable power-quality standard (MIL-STD-704 or DO-160 power sections, or equivalent).
- Components selected from manufacturers with adequate long-term availability commitment, or an explicit obsolescence mitigation plan noted for at-risk parts.

## Layout review checklist

- Minimum annular ring, trace/space, and other DRC parameters match the target IPC class's tighter Class 3 (or applicable class) values, not generic Class 2 defaults.
- Ground plane integrity and return-path continuity reviewed with EMI (MIL-STD-461-class) requirements in mind — no unnecessary plane splits under high-speed or high-current traces.
- Connector shield termination footprint supports 360° shield connection to chassis/enclosure ground, not a pigtail wire.
- Conformal coating mask/keepout areas defined on the fab/assembly drawing for connectors, test points, and any component that must remain uncoated.
- Rigid-flex bend regions (if used) meet minimum bend radius and have stiffeners placed at connector/solder-joint locations within or adjacent to the flex area.
- Traceability features (serial number field, date code, unique ID marking) included on silkscreen/assembly per program requirement.
