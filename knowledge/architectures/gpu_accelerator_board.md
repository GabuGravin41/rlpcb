---
title: GPU Accelerator Board Reference Architecture (Blackwell-Class Concept)
domain: high_performance_compute
tags: [gpu, blackwell, hdi, vrm, multiphase, pcie, power delivery, thermal, mezzanine, learning path]
applies_to: [gpu accelerator boards, ai training/inference cards, hpc mezzanine modules]
---

## Purpose of this guide

This describes the electrical architecture concept behind a data-center-class GPU accelerator board (the class NVIDIA Blackwell B200/GB200-generation and comparable AMD Instinct/data-center GPU cards represent), at the level needed to understand *why* these boards look the way they do, and to give an honest picture of what is and isn't realistic for a small team or an individual engineer to attempt. This is not a buildable reference design — it is orientation for understanding, evaluating, or working adjacent to this class of hardware, and for planning a realistic learning path toward high-speed digital design.

## System overview

A modern data-center GPU accelerator exists in two physical forms: a **PCIe add-in card** (a full-height card with a PCIe edge connector, seen in HGX/enterprise servers as well as some workstation contexts) or an **SXM/mezzanine module** (a small-form-factor board with a high-density board-to-board or socket connector, mounted directly onto a large system baseboard alongside several other identical modules and NVLink/interconnect switching — this is the GB200/HGX-class packaging). Both forms share the same core subsystems: the GPU package itself (a multi-die package with on-package HBM stacks), a very high current multiphase VRM, high-speed I/O (PCIe and/or proprietary GPU-to-GPU interconnect), power sequencing/management logic, and extensive telemetry.

## GPU package and memory

- The GPU die (or, in Blackwell's case, two reticle-limit dies connected by a very high-bandwidth die-to-die interconnect, presented to the system as one logical GPU) sits on a substrate alongside several stacks of HBM (High Bandwidth Memory) — HBM is not soldered as discrete DRAM packages on the PCB the way GDDR/DDR is; it's stacked directly on the same package substrate as the GPU die, connected via a silicon interposer, because the pin count and trace density HBM needs (thousands of signal connections per stack, extremely short reach) can only be achieved at package/interposer scale, not on ordinary PCB.
- What this means for the board: the PCB never sees individual HBM signal traces at all — the package presents a large, very fine-pitch BGA (or land-grid-array on some designs) to the PCB carrying power delivery pins, PCIe/interconnect high-speed signals, and low-speed management/telemetry signals. The extreme fine-pitch, high-pin-count package is itself the primary driver of everything unusual about this board class.

## Key part families (concept-level, not for small-team sourcing)

- **Multiphase VRM controllers**: high-phase-count digital multiphase controllers (e.g., Infineon/Renesas/MPS server-class VRM controller families) paired with integrated smart power stages combining FET half-bridges and gate drivers in one package.
- **PCIe redriver/retimer**: signal-conditioning ICs (e.g., Astera Labs, Parade, Texas Instruments retimer/redriver families) used to close the channel loss budget on Gen5/Gen6 PCIe traces.
- **BMC/sequencer**: baseboard management controller SoCs and power-sequencer ICs coordinating multi-rail bring-up order and PMBus telemetry aggregation.
- **HDI fabrication partners**: a small number of top-tier HDI-capable fabricators (concentrated in Taiwan, Japan, and Korea) qualified for the layer count, copper weight, and microvia complexity this class of board requires.

## Power delivery: the multiphase VRM

- Core voltage for a Blackwell-class GPU die is under 1 V (consistent with modern advanced-node logic supply voltages), while total package power draw is commonly in the 700 W–1200+ W range depending on the specific SKU and power cap configuration — at sub-1V core voltage and roughly a kilowatt of power, the core rail's current is on the order of 1000+ amps. This is the single most demanding power-delivery problem in mainstream digital electronics today.
- Delivering ~1000 A at under 1 V with acceptable efficiency and voltage regulation requires a **multiphase buck converter** with a very high phase count (commonly 16–20+ phases in current designs, sometimes implemented as multiple multiphase controllers each driving a phase group, coordinated together) — each phase individually might deliver several tens of amps, and phases are interleaved (switched with a phase-shifted timing pattern) so their combined ripple current largely cancels, reducing the output capacitance needed and easing the GPU package's own decoupling burden.
- **Power stage placement is package-proximity-driven, not just electrically convenient**: because the current is so large and the acceptable voltage droop under fast transient load steps is so tight (GPU workloads can swing load current by hundreds of amps within microseconds as compute units activate/idle), the power stages (the actual MOSFET half-bridges, often integrated "smart power stage" modules combining high-side/low-side FETs and a driver in one package) are placed as physically close to the GPU package as the board and component keepout allow — frequently ringing the package on multiple sides, sometimes on the board's back side directly beneath the package to shorten the power-delivery path through vias rather than lateral copper.
- **On-package or on-interposer decoupling** supplements board-level bulk/ceramic capacitance — the transient response budget is split across on-die decoupling (fastest, smallest energy), package-level decoupling capacitors (mounted on or very near the package substrate), and board-level ceramic/polymer capacitor banks (slower but higher total energy) — this multi-tier decoupling hierarchy is an extreme, compressed version of the same principle covered generally in power_decoupling_and_pdn.md, scaled up by roughly two to three orders of magnitude in both current and required capacitance.
- Voltage sensing uses **remote/differential sense** directly at the package's sense pins (not at the VRM's own output) so the control loop regulates the actual voltage the die sees, compensating for the unavoidable IR drop across the power-delivery path between VRM output and package — this is the same remote-sense principle used in any high-current point-of-load design, just with much higher stakes given the current level.

## PCB technology: HDI and layer count

- These boards use **HDI (High Density Interconnect)** construction with multiple sequential microvia build-up layers (commonly described in industry material as 12–26+ total layers depending on the specific board, with several sequential HDI lamination cycles) — the combination of the GPU package's extreme fine-pitch BGA and the sheer routing density needed (thousands of power-delivery vias plus high-speed PCIe/interconnect differential pairs plus HBM-adjacent short-reach signals) cannot be achieved with a standard single-lamination through-hole-via PCB; see bga_fanout_and_gpu_class_boards.md for the general BGA escape-routing and HDI microvia principles that scale up to this level.
- Copper weight and plane design for the power layers is unusually heavy (thick copper planes, sometimes with copper coin or embedded busbar structures in the most extreme designs) specifically to carry the roughly-1000 A core current without excessive I²R loss or thermal rise across the board's power-plane area — this is power_high_current_and_thermal.md's current-capacity/copper-sizing methodology pushed to its practical upper limit for a PCB (beyond which designs move to bonded copper busbars or vertical power-delivery structures rather than planar copper alone).
- Only a small number of PCB fabricators worldwide (concentrated among top-tier Taiwanese, Japanese, and Korean HDI specialists, plus a few others globally) can manufacture boards at this layer count, HDI complexity, and copper-weight combination with the yield and reliability data center customers require — this is genuinely not "pick a fab from a standard prototype house" territory; it involves qualified, audited manufacturing relationships and design-for-manufacturing collaboration specific to each fab's process capability.

## High-speed interfaces

- **PCIe Gen5/Gen6**: the host-facing interface (PCIe add-in card form factor) or an auxiliary management/bootstrap interface (mezzanine form factor, where the primary compute interconnect is often a proprietary GPU-to-GPU fabric rather than PCIe for the main data path) — PCIe Gen5 runs at 32 GT/s per lane, Gen6 introduces PAM4 signaling at 64 GT/s per lane; both require extremely tight loss budget, impedance control, and via stub management, well beyond what general-purpose PCIe design guidance in interfaces_usb_ethernet_pcie_ddr.md covers at the introductory level — Gen5/6-class routing typically needs channel simulation/signal integrity analysis software and often redriver or retimer ICs to close the link budget over any meaningful trace length.
- **GPU-to-GPU interconnect** (NVIDIA's NVLink or equivalent proprietary fabrics from other vendors): very high aggregate bandwidth, extremely short-reach, high-pin-count SerDes links between GPU packages on the same baseboard or across a switch — these are among the most demanding signal integrity challenges in the industry, generally requiring vendor reference designs and direct collaboration with the silicon vendor's SI team rather than independent design from public documentation alone.
- **High-speed board-to-board/mezzanine connectors**: extremely high pin-count, high-signal-density connectors (hundreds to over a thousand pins) carrying both the multiphase VRM's power delivery and the high-speed signal fabric between the module and baseboard — connector selection and the corresponding via/breakout design is itself a specialized discipline at this pin density.

## Power sequencing and telemetry

- Sequencing: the GPU package requires multiple rails (core, HBM, I/O, auxiliary) brought up and down in a specific order with specific timing relationships (often specified precisely by the silicon vendor) — implemented via a sequencer IC or an onboard microcontroller executing the vendor's specified sequence, monitoring each rail's power-good status before enabling the next.
- Telemetry: PMBus or a similar digital interface (see load_balancing_and_power_distribution.md for PMBus architecture principles) reports per-phase current, input/output voltage, and temperature from the VRM controller back to system management firmware (BMC) — this data feeds both protection (overcurrent/overtemperature shutdown) and data-center-level power capping/load-balancing across many GPUs in a rack.
- Thermal telemetry: multiple die-temperature sensors (often integrated in the GPU package itself) plus board-level thermal sensors near the VRM and memory feed both the GPU's own dynamic frequency/power throttling and the system's cooling control (fan speed or, increasingly at this power density, liquid-cooling cold-plate flow control).

## Thermal and mechanical

- At 700 W–1200+ W in a package roughly the size of a large postage stamp, air cooling alone is no longer sufficient for sustained full-load operation in most data-center deployments at this GPU class — liquid cooling (cold plates with coolant loops, sometimes full immersion in the highest-density deployments) is now standard for this power class, making the board's mechanical design (cold-plate mounting force, backplate rigidity to prevent package warp under mounting pressure) as significant an engineering problem as the electrical design.
- VRM power-stage thermal design also needs dedicated attention — at combined VRM power-stage losses potentially in the tens of watts even at good efficiency, and packed densely around the GPU package, the VRM's own cooling (often sharing the same cold plate or an adjacent dedicated heatsink) is a real thermal-budget item, not an afterthought.

## What is realistically feasible for a small team

Be direct about this with anyone planning work in this space:

- **Not feasible for an individual or small team without major institutional backing**: designing, fabricating, and bringing up an actual Blackwell-class GPU board. This requires: an NDA relationship with the GPU/HBM vendor (these packages are not available as off-the-shelf purchasable components to small teams), access to specialized HDI fabrication capacity that requires qualification and typically large minimum order volumes, six- to seven-figure NRE (non-recurring engineering) budgets for tooling, signal integrity simulation licenses and expertise, and a multi-person team spanning power electronics, high-speed digital, mechanical/thermal, and firmware/BMC disciplines. This is genuinely enterprise/hyperscaler-tier work.
- **What individual engineers realistically do in this space**: work at established companies (GPU vendors, hyperscalers, ODMs like Foxconn/Quanta/Wistron building these boards under contract, or component vendors supplying VRM controllers/power stages/connectors into this market) where the institutional infrastructure (fab relationships, vendor NDAs, simulation tools, senior SI mentorship) already exists — the individual contributes a piece (VRM design, SI analysis of one interface, thermal simulation) within that infrastructure, not the whole board alone.
- **A realistic, buildable learning path toward these skills**:
  1. Master standard multilayer PCB design and basic power delivery on affordable, well-documented platforms (an STM32/ESP32-class board, following microcontroller_and_fpga_boards.md and power_buck_boost_converters.md).
  2. Build a multiphase VRM project at a modest scale (e.g., a 2–4 phase buck delivering tens of amps at low voltage for an FPGA or GPU-adjacent hobbyist board) to learn multiphase control, current sharing, and transient response hands-on with hardware you can actually fabricate and test on a bench.
  3. Design a PCIe Gen3 or Gen4 add-in card around a mid-range FPGA (widely available development-kit-class parts) — this teaches real PCIe link training, controlled-impedance routing, via stub management, and basic signal integrity measurement (TDR, eye diagrams on a decent oscilloscope) at a scale and cost an individual or small team can actually execute and iterate on.
  4. Progress to HDI design fundamentals via bga_fanout_and_gpu_class_boards.md and a project with a genuinely fine-pitch BGA (many modern FPGAs and SoCs already require HDI at 0.5mm-or-finer pitch), using a fab that offers HDI prototyping (several mainstream prototype fabs, including JLCPCB and PCBWay, now offer limited HDI/microvia service — see fab_order_checklist.md — though not at data-center-GPU complexity/volume).
  5. Study public technical material from GPU/HPC vendors and conference talks (Hot Chips, OCP Summit presentations on GPU baseboard/power-delivery architecture are often public) to understand the concepts at this guide's level of depth, while recognizing that the detailed implementation knowledge (exact stackups, controller tuning, vendor-specific package requirements) is proprietary and NDA-gated.
  6. If the goal is a career path into this specific field, target roles at GPU vendors, hyperscalers' hardware teams, or ODMs building this class of hardware — the domain-specific skills (extreme multiphase VRM design, PCIe Gen5/6 SI, HDI-at-scale) are learned on the job with access to tools and mentorship a small team or individual cannot replicate independently.

## Safety and standards references

- IEC 62368-1 for general electronic equipment safety at the finished-system level; PCIe-IF and OCP (Open Compute Project) specifications for mechanical/electrical interoperability of accelerator cards and baseboards in data-center deployments.
- Data-center liquid cooling introduces its own safety/reliability considerations (leak detection, coolant compatibility with PCB materials and connectors) that are a systems-engineering concern beyond this board's own schematic/layout scope.

## Common failure modes (at the architecture-understanding level)

- Underestimating that HBM is a package-level, not board-level, integration — a board design cannot "add more memory" without redesigning the package/substrate, a common misconception for engineers used to board-level DDR/GDDR design.
- Assuming a standard prototype PCB fab can produce this class of board — the combination of layer count, HDI complexity, copper weight, and controlled-impedance tolerance at PCIe Gen5/6 speeds is outside general prototype fab capability.
- Treating the VRM as a scaled-up version of a laptop/desktop CPU VRM without recognizing the qualitatively different transient response and remote-sense requirements at this current level.
- Neglecting mechanical/thermal co-design (cold-plate mounting force, backplate warp control) as a "later" concern rather than a first-order design driver from the start of the layout.

## Review checklist (conceptual — for evaluating or discussing a design at this level, not a buildable checklist)

- [ ] Power delivery path from VRM output to package sense pins analyzed for IR drop and remote-sense compensation, not assumed negligible.
- [ ] Multiphase VRM phase count and interleaving verified against the GPU's actual transient load-step specification, not a generic multiphase reference design.
- [ ] Decoupling hierarchy (on-die, on-package, board-level) sized against the silicon vendor's published transient response requirement.
- [ ] PCIe Gen5/6 or interconnect channel loss budget verified via simulation against the actual stackup/via structure, not assumed from a generic impedance target alone.
- [ ] Power sequencing order and timing verified against the exact vendor-specified rail bring-up sequence.
- [ ] Thermal/mechanical design (cold plate, backplate) co-developed with the electrical layout from the start, not treated as a downstream mechanical-only task.
