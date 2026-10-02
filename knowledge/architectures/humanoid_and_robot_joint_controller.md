---
title: Humanoid and Robot Joint Controller Reference Architecture
domain: robotics
tags: [foc, bldc, joint controller, encoder, current sense, ethercat, can-fd, thermal, high density, robot compute]
applies_to: [robot joint driver boards, humanoid actuator boards, robot main compute boards]
---

## Two board classes covered

This guide covers two distinct but related board types found in a modern robot/humanoid system: the **joint/actuator controller** (compact FOC BLDC driver co-located at or very near each joint) and the **robot main compute board** (central processing, sensor fusion, and high-level motion planning, communicating with many joint controllers over a shared bus).

## Joint controller: system overview

A joint controller integrates a 3-phase FOC inverter, current sensing, gate drivers, an angle sensor interface, local closed-loop current/velocity/position control firmware, and a fieldbus interface into the smallest practical footprint, since it usually mounts inside or immediately adjacent to the joint housing itself. This differs from a general motor_drives_and_motion.md industrial drive mainly in extreme size/thermal constraints and typically higher control-loop bandwidth requirements (robot joints often run current loops at tens of kHz and need low-latency torque response for compliant/force-controlled motion).

## Key part families

- **Gate drivers**: 3-phase gate driver ICs (e.g., TI DRV8323/DRV8353-class, onsemi/Infineon 3-phase drivers) or discrete half-bridge drivers for GaN-based designs.
- **Power devices**: high-current-density MOSFETs for 24-48 V designs, GaN FETs (e.g., EPC, Navitas, TI GaN families) for the most compact/high-frequency joints.
- **Angle sensors**: magnetic absolute encoder ICs (e.g., AMS AS5047/AS5048-class, TDK/Renesas magnetic angle sensors) or optical absolute encoders for higher-precision joints.
- **Current sense amplifiers**: precision low-side shunt amplifiers (e.g., TI INA240-class) with high common-mode rejection and PWM-synchronized bandwidth.
- **Fieldbus**: EtherCAT slave controller ASICs (e.g., Beckhoff ET1100/ET1200-class) or CAN-FD transceivers (e.g., TI, Microchip, NXP CAN-FD families).
- **Robot compute**: applications processors/SoMs (e.g., NVIDIA Jetson-class modules for vision/AI-heavy designs, or ARM Cortex-A SoCs) paired with a real-time MCU/FPGA for deterministic bus scheduling.

## Joint controller power tree

- Bus voltage: commonly 24–48 V for small/medium robot joints, up to 60–80 V for larger humanoid leg/hip actuators needing higher power density — chosen as a tradeoff between wire gauge/current (lower voltage = higher current for the same power, meaning thicker harness and connector) and available FET/driver voltage ratings.
- Local logic supply: a small buck converter (or two — one for the MCU/digital core at 3.3 V, one for gate-driver bias at 12–15 V) derived from the joint bus voltage — size for efficiency, since every joint's quiescent+switching loss adds to the robot's total power/thermal budget and, for a walking humanoid, to battery runtime.
- Current sense reference and any isolated telemetry supply follow motor_drives_and_motion.md shunt-sensing guidance — most joint controllers use non-isolated low-side shunt sensing referenced to local ground rather than isolated sensing, since the joint bus itself isn't safety-isolated from logic in most designs (unlike mains-connected industrial drives).
- Bulk/local decoupling: because joint controllers are physically distant from the central battery/power-distribution board (see load_balancing_and_power_distribution.md and ups_and_battery_backup.md for the source side), local bulk capacitance at each joint must absorb the fast current transients of FOC switching without relying on a low-impedance path back to the central supply — undersized local bulk capacitance on a long, inductive harness run is a common source of bus-voltage ringing/instability in multi-joint robots.

## Joint controller: inverter and gate drive

- 3-phase inverter: typically integrated gate-driver + MOSFET modules or discrete gate driver IC (e.g., three half-bridge driver or a single 3-phase gate driver IC) driving discrete power MOSFETs — GaN FETs are increasingly used in the most compact/high-power-density joints for their smaller size and lower switching loss at the tens-of-kHz-to-100kHz+ PWM frequencies some high-bandwidth current loops use.
- Follow motor_drives_and_motion.md directly for bootstrap/isolated gate supply choice, dead-time selection, and hot-loop minimization — hot-loop area is even more critical here than in a larger industrial drive because board area is at a premium and parasitic inductance from a necessarily-cramped layout directly costs switching margin/EMI performance.
- Current sensing: low-side per-phase (two or three shunt) sensing is standard for joints needing accurate torque control across the full speed/modulation range (see motor_drives_and_motion.md) — shunt resistance and amplifier gain chosen for the joint's rated current with adequate ADC resolution at both low (fine torque control at near-zero speed, common in compliant robot joints) and peak (short-duration high-torque) current.

## Joint controller: angle sensing

- **Magnetic absolute encoder ICs** (e.g., AMS/ams-OSRAM AS5047/AS5048-family or similar Hall-based or inductive angle sensor ICs) reading a diametrically magnetized magnet on the motor shaft are the dominant choice for compact joints — SPI or SSI/BiSS-C digital output, no mechanical contact, small footprint, and absolute position on power-up (critical for a robot joint since re-homing every joint on every power cycle is impractical).
- Sensor placement precision matters: these ICs require the magnet centered within a tight axial/radial tolerance (datasheet-specified, often sub-mm) for rated accuracy — mechanical design and PCB placement must agree on this tolerance stack-up, not just electrical connection.
- **Dual-sensor architectures** (motor-side high-resolution encoder plus output-side/joint-side lower-resolution absolute encoder, common in geared joints) let the controller separately measure motor rotation (for commutation/high-bandwidth current control) and actual joint output angle (which differs from motor angle by gearbox backlash/compliance) — needed for accurate force/torque control through a gearbox or harmonic drive, not just position control.
- Route angle-sensor SPI/analog signals away from the inverter's switch-node copper and phase output traces, same principle as motor_drives_and_motion.md encoder guidance, doubly important given the short physical distances involved in a compact joint board.

## Joint controller: thermal management

- Thermal density is the dominant layout constraint: a joint controller often has only a few cm² of board area and limited airflow (enclosed joint housing), while dissipating several watts continuously (inverter conduction/switching loss plus motor I²R reflected as heat into the housing) — this exceeds what natural convection alone handles at typical humanoid continuous-torque operating points.
- Mitigation techniques: thick copper (2 oz or heavier) power/ground planes acting as heat spreaders, an array of thermal vias under the FET/driver package connecting to a bottom-side copper pour or directly to a metal joint housing (thermal interface material between board and housing structure is common), and, where the mechanical design allows, direct FET-to-housing thermal paths bypassing the PCB entirely.
- Worst-case thermal analysis must include heat conducted *into* the board from the adjacent motor (the motor itself often runs hotter than the board under sustained torque) — a board rated only against its own dissipation without accounting for motor-conducted heat will under-predict real operating temperature, a known failure mode called out in motor_drives_and_motion.md.
- Thermal derating and shutdown: an onboard temperature sensor (thermistor or the driver IC's integrated thermal sense) feeding into a firmware or hardware thermal foldback (reducing commanded current as temperature approaches a limit) is standard practice, since letting the joint hard-fault-off mid-motion is often worse for the robot's stability/safety than gracefully reducing torque.

## Joint controller: communication and daisy-chaining

- **EtherCAT**: preferred where hard real-time determinism and rich telemetry (streaming torque, position, current, temperature from every joint each cycle) are needed — each joint board carries an EtherCAT slave controller with two PHY ports for daisy-chaining, matching plc_controller_and_io_modules.md's daisy-chain backplane philosophy applied to a robot's joint chain.
- **CAN-FD**: common in cost- or connector-constrained designs, or where full EtherCAT-class determinism isn't required — higher data rate than classic CAN (up to several Mbps) supports richer per-joint telemetry than classic CAN's 8-byte frames allowed.
- Harness design: a multi-joint robot's joint-to-joint or joint-to-spine wiring is a significant mechanical/reliability concern (flex life over repeated joint motion) — use connectors and cable rated for the expected flex-cycle count, and route the bus/power harness to minimize strain at joint pivot points.

## Robot main compute board: overview

- Central processing: typically an applications processor or SoC (e.g., an ARM-based SoC or, for vision/AI-heavy humanoids, a GPU-integrated module such as an NVIDIA Jetson-class module) running perception, planning, and high-level motion coordination, communicating down to joint controllers over the shared EtherCAT/CAN-FD network.
- Sensor fusion inputs: IMU (often multiple — one at the torso/central compute, sometimes one per limb segment for whole-body state estimation), force/torque sensors at end-effectors or feet, cameras/depth sensors for perception — each following its own interface guide (analog_and_mixed_signal.md for analog sensor front ends, interfaces_usb_ethernet_pcie_ddr.md for camera/high-speed sensor links).
- Real-time coordination: many architectures pair the applications processor with a real-time MCU or FPGA that handles the deterministic EtherCAT master/CAN-FD scheduling and safety-relevant monitoring (e.g., a watchdog that can command all joints to a safe torque-off state), keeping this function isolated from the less deterministic main compute OS scheduling — same separation-of-concerns principle as plc_controller_and_io_modules.md's CPU-module A-core/M-core split.
- Power distribution to joints: the main compute board (or a dedicated power distribution board — see load_balancing_and_power_distribution.md) fans out the main battery bus to each joint controller, typically with per-branch fusing/eFuse protection and, in larger humanoids, per-limb power switching so a single limb can be isolated for service or fault containment without shutting down the whole robot.

## Layer count and stackup

- Joint controller: 6–8 layers is now common in compact high-density joints (despite the small size) specifically to get a dedicated ground/power plane pair plus separated signal layers within a very constrained footprint — layer count is driven by density/thermal-via routing needs more than raw signal speed. See stackup_and_layer_count.md and bga_fanout_and_gpu_class_boards.md for fine-pitch/dense component fanout principles that apply to the angle-sensor IC and any BGA-package MCU.
- Main compute board: 8–12+ layers typical for a modern applications-processor/SoC design with DDR memory and PCIe-class peripherals — see interfaces_usb_ethernet_pcie_ddr.md and bga_fanout_and_gpu_class_boards.md directly.

## Placement and routing priorities (joint controller)

1. Inverter hot loop (bus capacitor–FETs–phase output) minimized above all else given the extreme space/thermal constraint — this is the single highest-leverage layout decision on the board.
2. Angle-sensor IC placed and oriented per the mechanical drawing's magnet-to-sensor tolerance, verified against the actual joint housing CAD, not just schematically connected.
3. Shunt current-sense traces routed as short Kelvin pairs directly to the sense amplifier, away from phase-output copper.
4. Thermal via array placed under every significant heat source (FETs, driver IC, shunt resistors) connecting to the heat-spreading plane/housing interface.
5. EtherCAT/CAN-FD connector placement oriented for the physical daisy-chain cable path within the joint housing's mechanical envelope.

## Safety and standards

- No single universal standard governs humanoid/robot joint electronics the way EN 81-20 governs elevators; relevant reference points include ISO 10218 (industrial robot safety) and ISO/TS 15066 (collaborative robot force/power limits) for robots operating near humans, and general functional-safety frameworks (IEC 61508/ISO 13849) for any safety-rated stop function.
- Torque/force limiting (whether for collaborative safety or simply to protect the mechanism) should have a hardware or low-level firmware enforced current limit independent of high-level planning software, so a planning bug cannot command unlimited joint torque.
- A robot-wide hardwired e-stop, gating power/enable to all joint controllers simultaneously (not just a network command each joint must individually honor), is standard practice for any robot large/powerful enough to pose a hazard — mirrors the conveyor_and_motion_controller.md e-stop principle.

## Test and bring-up plan

1. Bench-power a single joint controller with the motor mechanically free (no load), current-limited supply, verify gate-drive and current-sense signals on a scope before closing any control loop.
2. Verify angle sensor readback against a known mechanical reference (manually rotate to marked positions) before trusting it for closed-loop commutation.
3. Close the current loop first (torque control) at low commanded current, then velocity loop, then position loop — standard cascaded-loop bring-up order, each verified stable before enabling the next.
4. Thermal-image the board under sustained rated current to find actual hot spots versus predicted, checking especially for motor-conducted heat effects noted above.
5. Bring up the fieldbus daisy-chain incrementally (one joint, then two, then the full chain) verifying each joint enumerates and reports telemetry correctly before scaling to the full robot.
6. System-level e-stop test: trigger the hardwired e-stop during active motion and verify every joint reaches a safe torque-off/brake state within the expected reaction time, not just the joint nearest the e-stop switch.

## Common failure modes

- Angle sensor magnet misaligned relative to the sensor IC due to a mechanical tolerance stack-up not caught until integration, causing commutation errors under load.
- Local bulk capacitance undersized for a joint far down a long, inductive power harness, causing bus ringing/current-loop instability that doesn't appear on a short bench power lead.
- Thermal design validated only against the board's own dissipation, missing conducted heat from an adjacent hot motor under sustained torque.
- EtherCAT/CAN-FD bus signal integrity degraded by cramming the transceiver too close to the switching inverter without adequate isolation/routing separation, given the extreme space constraints.
- Torque limiting implemented only in high-level planning software, with no low-level hardware/firmware enforced current limit as a backstop.
- E-stop implemented as a network message each joint must individually receive and act on, rather than a hardwired power/enable cutoff, risking a joint that misses the message continuing to move.

## Schematic review checklist

- [ ] Inverter gate drive, dead time, and current-sense topology follow motor_drives_and_motion.md with values justified for this joint's actual current/frequency, not copied from a different design.
- [ ] Angle sensor interface (SPI/SSI) and its power supply are clean and separated from switching noise sources.
- [ ] Low-level current/torque limit enforced in firmware or hardware independent of high-level motion-planning software.
- [ ] Thermal sensor present and wired into a foldback/shutdown path, not just a logged telemetry value.
- [ ] E-stop/safe-torque-off input is a hardwired power/enable path, not solely a network message the joint firmware must interpret.
- [ ] Local bulk capacitance sized for the joint's actual harness inductance and current transients, not a generic value.

## Layout review checklist

- [ ] Inverter hot loop area minimized as the top layout priority given board-area constraints.
- [ ] Angle-sensor IC placement/orientation verified against actual mechanical CAD magnet position and tolerance.
- [ ] Thermal via array under every significant heat source, connected to a heat-spreading plane or housing interface.
- [ ] Current-sense Kelvin traces short and routed away from phase-output copper.
- [ ] EtherCAT/CAN-FD connector and cable routing oriented for the actual physical daisy-chain path within the joint housing.
- [ ] Board and component placement account for motor-conducted heat, not just onboard dissipation, in thermal validation.
