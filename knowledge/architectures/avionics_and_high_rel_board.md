---
title: Avionics and High-Reliability Board Reference Architecture
domain: aerospace
tags: [avionics, do-254, do-160, mil-std-461, mil-std-704, redundancy, derating, conformal coat, high reliability]
applies_to: [flight computer boards, avionics interface boards, high-reliability industrial/aerospace controller boards]
---

## Scope

This guide covers general engineering principles for flight-computer-style and other high-reliability avionics boards, referencing public standards by name and purpose only. It contains no export-controlled, ITAR-restricted, or weapons-specific content — nothing here goes beyond publicly available general engineering practice taught in avionics design coursework and published standards summaries. A real avionics program requires engagement with a DER (Designated Engineering Representative) or equivalent certification authority, full standard text (purchased/licensed), and a qualified test house — this guide supports conceptual understanding, not a certification pathway.

## System overview: redundancy as the organizing principle

Avionics architecture is dominated by one idea more than any other: **no single failure should cause loss of the function**. This shapes everything from power architecture to processor selection to connector choice, and it's the main way avionics design differs from even careful industrial design.

- **Redundant channels**: flight-critical functions (flight control computation, critical sensor reading, critical actuator command) are implemented on two or more independent channels (commonly called "lanes"), each with its own processor, its own power supply, and often its own sensor set, so a single hardware or software fault in one lane doesn't propagate to the others.
- **Dissimilar redundancy**: in the highest-criticality designs, redundant lanes deliberately use different processor architectures, different compilers/toolchains, or even different design teams for the software — reducing the chance a common-mode fault (a shared silicon erratum, a shared compiler bug) defeats the redundancy that otherwise looks complete on paper. This is expensive and reserved for the highest design assurance levels; understand it as a concept even where a specific project doesn't reach that level of rigor.
- **Voting/monitoring architecture**: multiple lanes' outputs are compared (voted) by a monitor function — a 2-out-of-3 voting scheme (triplex) can identify and outvote a single faulty lane; a simpler dual-lane "command/monitor" architecture has one lane commanding the actuator while the other independently monitors and can disable the commanding lane if it disagrees beyond a threshold.

## Key part families

- **Processors**: radiation-tolerant or extended-temperature-qualified processor families (e.g., automotive/aerospace-qualified Cortex-A/M parts, or specialized rad-hard processors for the highest-criticality programs) selected for the platform's DAL and environmental category.
- **Power supervisors**: high-reliability voltage supervisor/sequencer ICs with tight, qualified threshold accuracy for redundant-lane power monitoring.
- **Connectors**: circular vibration-rated connectors (e.g., MIL-DTL-38999-style) and positively-latching board-to-board connectors for all vibration-exposed interfaces.
- **Passives**: automotive/mil-qualified (AEC-Q200-class or higher) resistors, capacitors, and inductors selected specifically for derating margin and extended temperature range rather than commercial-grade default parts.
- **Isolation/EMI filtering**: qualified common-mode chokes and filtered power-entry modules meeting the applicable MIL-STD-461/DO-160 EMI category.

## DO-254 and design assurance level (conceptual)

- **DO-254** ("Design Assurance Guidance for Airborne Electronic Hardware") governs the *process* used to design complex custom hardware (FPGAs, ASICs, and by extension the boards containing them) for airborne use — it's a process/documentation standard, not a set of electrical design rules, but it directly shapes how a board is designed: requirements traceability (every design decision traces to a documented requirement), verification coverage (every requirement has a corresponding verification/test), and configuration management (every design artifact under strict version control) are the practical outputs.
- **Design Assurance Level (DAL)**, from DAL A (catastrophic failure condition — loss of the aircraft) down to DAL E (no safety effect), determines how rigorous the DO-254/DO-178 (the analogous standard for software) process must be for a given function — a DAL A flight control computer requires far more extensive verification, redundancy, and independent review than a DAL D cabin-entertainment interface board, even though both might be "avionics."
- For hardware engineers, the practical DO-254 impact on board design is: design decisions and component selections must be documented and traceable, complex programmable logic (FPGA) design needs its own verification plan (simulation coverage, not just "it worked on the bench"), and any design change after a baseline is established goes through formal change control rather than an informal "quick fix."

## DO-160 environmental qualification

- **DO-160** ("Environmental Conditions and Test Procedures for Airborne Equipment") specifies the environmental test regime a board/box must survive — temperature/altitude, vibration, humidity, fluid contamination, power input transients, and EMI/lightning-related sections, each identified by a section letter (e.g., Section 4 temperature/altitude, Section 8 vibration, Section 16 power input, Section 21 emission of RF energy, Section 22 lightning induced transient susceptibility).
- **Practical design impact**: components must be rated (and, for the highest-criticality programs, individually qualified/tested) across the full DO-160 temperature range for the equipment's installation category (which varies by where in the aircraft it's mounted — e.g., pressurized cabin vs. unpressurized/uncontrolled bay has a much wider extreme), vibration mounting and component retention (staking/conformal coat, connector locking mechanisms, no reliance on friction-fit connectors) must survive the specified vibration profile, and power input circuitry must tolerate the specified transient/surge/dropout conditions without malfunction beyond the allowed category.
- **Section 16 power input characteristics**: aircraft power (commonly 28 VDC or 115 VAC 400 Hz in many platforms) has defined normal, abnormal, and emergency operating ranges plus transient/surge specifications the equipment's power supply must tolerate without damage and, depending on category, without functional interruption — this drives significant input-stage design margin (input voltage range, transient clamping, hold-up capacitance) well beyond what a typical industrial 24 VDC design assumes.

## MIL-STD-461 (EMI) and MIL-STD-704 (power quality) — general concepts

- **MIL-STD-461** specifies conducted and radiated emissions and susceptibility limits for military electronics, organized into test categories (CE for conducted emissions, RE for radiated emissions, CS for conducted susceptibility, RS for radiated susceptibility) — while written for military platforms, its general EMC design principles (shielding, filtering, grounding architecture) are widely referenced in high-reliability aerospace design generally, and its structure parallels the commercial DO-160 EMI sections. Design-level implications: filtered power entry (common-mode/differential-mode EMI filters at every external power interface), shielded enclosures with defined shield continuity/grounding at connector interfaces, and cable shielding/termination practices that avoid pigtail connections (a shield terminated through a long lead wire) which significantly degrade high-frequency shielding effectiveness.
- **MIL-STD-704** specifies the electrical characteristics of aircraft electric power (voltage/frequency ranges, transients) that utilization equipment must accept — conceptually parallel to DO-160 Section 16 but written for the military-platform context; the practical design lesson is the same: power input stages need substantially wider tolerance and transient immunity than commercial/industrial equivalents, verified against the specific standard revision and power category the platform specifies.
- Treat both standards as defining a **much harsher electrical and EMI environment** than commercial industrial equipment normally assumes — an avionics power input design that "works" against a typical 24 VDC industrial supply's tolerances is very likely inadequate for either standard's transient/surge requirements without explicit redesign and margin analysis.

## Component derating

- High-reliability design applies **derating**: operating every component well below its absolute maximum rating (not just within the "recommended operating" range) to extend life and improve margin against manufacturing variation and environmental extremes — this is a documented, program-specific practice (many aerospace primes and standards bodies, e.g., NASA/JPL derating guidelines, publish specific derating tables) rather than a single universal number, but common rules of thumb include: resistors derated to well under their rated power dissipation (often 50% or less of rated power at max ambient), capacitors derated on voltage (commonly to 50–70% of rated voltage, tighter for ceramics near their temperature-coefficient knee and for tantalum capacitors given their surge-current failure mode), and semiconductors derated on voltage, current, and junction temperature margin relative to absolute maximum ratings.
- Derating interacts directly with thermal design: a component operating at a lower fraction of its rated dissipation runs cooler for the same ambient, directly improving both immediate reliability and long-term wearout-driven failure rate (many failure mechanisms follow an Arrhenius-type acceleration with temperature) — thermal margin and electrical derating are two views of the same reliability lever, not separate concerns.
- Tantalum capacitor derating deserves specific mention: tantalum capacitors have a known catastrophic (ignition-risk) failure mode under voltage/surge-current stress near their rated voltage, which is why high-reliability designs derate tantalum voltage more aggressively than ceramic, and often prefer MnO2-free "wet" or polymer tantalum variants with better surge tolerance, or avoid tantalum entirely in favor of ceramic/polymer alternatives where the application allows.

## Conformal coating and staking

- Conformal coating (see industrial_plc_io.md for the general material tradeoffs — acrylic, urethane, silicone, parylene) is standard practice on avionics boards for humidity, contamination, and fungus resistance, with material choice driven by the specific DO-160 humidity/fluid-contamination category and any program-specific material specification (e.g., MIL-I-46058C or its successors, still commonly referenced for coating material qualification even in commercial aerospace programs).
- **Staking**: a bead of adhesive (often a flexible epoxy or RTV silicone) applied at tall/heavy components (connectors, large capacitors, inductors, crystal oscillators) to mechanically secure them against the vibration environment beyond what solder joints alone reliably survive — this is a standard, expected step in high-vibration-qualified assemblies, not an optional extra, and staking material/placement should be specified on the assembly drawing, not left to assembly-technician judgment.
- Connector selection favors locking, vibration-rated connector families (e.g., MIL-DTL-38999-style circular connectors, or board-to-board connectors with positive latching) over friction-fit or simple pin-header connectors for anything in a vibration-exposed location.

## Power architecture

- Redundant power feeds: critical avionics boards commonly accept two independent aircraft power feeds (e.g., from separate electrical buses) with onboard ORing (see load_balancing_and_power_distribution.md for the ORing principle, applied here for availability rather than current-sharing efficiency) so loss of one aircraft bus doesn't remove power from the critical function.
- Input protection: transient/surge protection sized for the specific DO-160/MIL-STD-704 power-quality category, with hold-up capacitance sized to ride through specified dropout durations without a processor reset — a processor reset during a brief power transient is itself a failure condition for a flight-critical function, so hold-up time is a real specified design parameter, not a nice-to-have.
- Isolated, independently-fused supplies per redundant lane, following the same "no shared single point of failure" principle applied throughout the power architecture, not just the processor/software architecture.

## Layer count and stackup

- Flight computer class boards: typically 8–14+ layers depending on processor/memory complexity, with explicit layer allocation for redundant-lane separation (some programs physically separate redundant lanes' power and ground planes, not just their signal routing, to limit common-mode coupling between lanes) — see stackup_and_layer_count.md for general stackup principles, applied here with an added redundancy-isolation constraint layered on top of normal signal-integrity stackup planning.
- Simpler avionics interface boards (sensor interface, discrete I/O): 4–6 layers, following similar isolation/derating principles at smaller scale.

## Placement and routing priorities

1. Redundant lanes physically separated on the board (distinct board regions, sometimes with a designed-in physical/thermal barrier) to reduce the chance of a single localized event (connector damage, localized overheating, a dropped tool during assembly) affecting more than one lane.
2. Power entry and EMI filtering placed immediately at each external power connector, following the same "protection right at the boundary" principle as industrial_plc_io.md's TVS placement guidance, scaled to the relevant DO-160/MIL-STD-461 category.
3. Staking points identified on the layout/assembly drawing for tall or heavy components before board fabrication, not added ad hoc during assembly.
4. Test points provided for every critical signal needed for both production test and later fault-isolation/maintenance, since field/depot repair access is often far more constrained than a lab bench.
5. Connector selection and placement favor vibration-rated, keyed, positive-latching parts, oriented and mounted to minimize cantilevered mechanical stress on the PCB.

## Test and bring-up plan

1. Bench bring-up on current-limited lab supplies exactly as any board (see bring_up_and_test_checklist.md), but with derated component stress verified against the design's derating targets, not just functional pass/fail.
2. Environmental screening: temperature cycling and, where the program requires it, vibration screening (even a basic random-vibration test on a shaker table) early in the prototype phase catches marginal solder joints, connector seating, and staking effectiveness before committing to a design baseline.
3. Redundancy fault injection: individually disable/fail each redundant lane (power removal, forced fault injection) and verify the remaining lane(s) correctly assume the function and the voting/monitoring logic correctly identifies and isolates the faulted lane.
4. Power-quality susceptibility testing against the applicable DO-160 Section 16 or MIL-STD-704 transient profile, verifying the power input stage's actual behavior (not just simulated) against the specified transient categories.
5. EMI pre-compliance testing against the applicable MIL-STD-461 or DO-160 EMI sections before formal qualification testing at an accredited test house.
6. Full DO-254/DO-160 qualification testing and certification-authority review, for any board actually intended for installation on a certified aircraft — this is a formal, external process beyond internal bring-up.

## Common failure modes

- Redundant lanes sharing an unrecognized common-mode failure point (a shared power connector, a shared clock source, a shared physical location vulnerable to a single localized fault) that defeats the intended independence.
- Tantalum capacitors used near their rated voltage without adequate derating, creating a latent ignition-risk failure mode under a transient surge event.
- Conformal coating or staking omitted or under-specified, leading to vibration-induced solder joint or connector failures discovered only in qualification testing (or worse, in service).
- Power input stage designed against a "typical" transient assumption rather than the actual specified DO-160/MIL-STD-704 category, failing qualification testing.
- DO-254 traceability treated as after-the-fact paperwork rather than a design discipline from the start, causing expensive rework to reconstruct requirements-to-verification traceability late in a program.
- Friction-fit connectors used in a vibration-exposed location, working fine on the bench but failing intermittently in actual flight vibration environments.

## Schematic review checklist

- [ ] Redundant lanes have independent power, and any shared component/connector has been explicitly reviewed as an accepted common-mode risk, not an oversight.
- [ ] Component derating (voltage, current, power, temperature) checked against the program's derating guideline for every part, not just the highest-stress parts.
- [ ] Power input stage designed and verified against the specific DO-160/MIL-STD-704 category and transient profile applicable to the installation.
- [ ] Tantalum capacitors (if used) derated appropriately for surge-current tolerance, or replaced with ceramic/polymer alternatives where suitable.
- [ ] EMI filtering present at every external interface per the applicable MIL-STD-461/DO-160 EMI section.
- [ ] Test points provided for every signal needed for production test and field fault isolation.

## Layout review checklist

- [ ] Redundant lanes physically separated on the board with distinct power/ground plane regions where the program requires lane isolation.
- [ ] Staking points for tall/heavy components identified on the assembly drawing.
- [ ] Connector selection is vibration-rated and positively latching for all vibration-exposed locations.
- [ ] Power entry and EMI filtering placed immediately at the connector, before any sensitive circuitry.
- [ ] Conformal coating mask/keepout defined for connectors, test points, and any component requiring later access.
- [ ] Thermal design supports the component derating targets at the specified installation's worst-case ambient/altitude condition.
