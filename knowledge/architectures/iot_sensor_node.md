---
title: IoT Sensor Node Reference Architecture
domain: iot
tags: [esp32, nrf52, low power, battery, antenna, sensor node, sleep current, ble, lora]
applies_to: [iot sensor node boards, battery-powered wireless sensor boards, esp32/nrf boards]
---

## System overview

A battery-powered IoT sensor node reads one or more sensors, processes/stores data locally, and periodically transmits over a wireless link, spending the overwhelming majority of its life in a deep-sleep state to achieve multi-month-to-multi-year battery life from a small cell. The entire architecture is organized around minimizing average current draw, since a node that works perfectly but drains its battery in three weeks has failed its actual requirement.

## Processor and radio selection

- **ESP32-class (Xtensa or RISC-V, integrated Wi-Fi + BLE)**: appropriate when the deployment has Wi-Fi infrastructure to connect to directly (no separate gateway needed) or when BLE connectivity to a phone/hub is sufficient — strongest choice when ease of development, existing library ecosystem, and moderate (not extreme) power budget are priorities. ESP32 active/TX current is meaningfully higher than a dedicated low-power BLE SoC, so deep-sleep duty cycling is essential for battery life; ESP32 deep-sleep current is commonly in the low tens of µA range (varies by exact variant and RTC memory retention configuration) — still far higher than the sub-µA sleep current the most aggressive nRF-class designs achieve.
- **nRF52/nRF53-class (Nordic, BLE/Thread/Zigbee, ARM Cortex-M4/M33)**: the dominant choice for the most power-sensitive designs — sub-µA to low-single-digit-µA sleep current, efficient BLE radio, and a mature low-power peripheral/DMA architecture (peripherals can operate with the CPU asleep in many configurations) purpose-built for coin-cell/multi-year battery targets. Requires more careful firmware architecture (event-driven, interrupt/DMA-based rather than polling) to realize the low-power potential — a naive port of ESP32-style polling firmware onto an nRF part will not achieve the part's rated sleep current.
- **LoRa/LoRaWAN modules** (often a separate radio IC or module, e.g., Semtech SX126x-class, paired with either processor family): chosen when the deployment needs long range (km-class, building/campus/rural coverage) at very low data rate rather than short-range high-bandwidth connectivity — appropriate for infrequent, small-payload sensor reports (temperature, tank level, asset tracking) where BLE/Wi-Fi's range is insufficient and a LoRaWAN gateway infrastructure exists or is being deployed alongside the nodes.
- **Cellular (NB-IoT/LTE-M) modules**: chosen when no local gateway/infrastructure exists and direct cellular connectivity is acceptable for the power/cost budget — cellular modules draw substantially more current during connection/transmission than BLE or LoRa, so the duty-cycle/reporting-interval design must account for this explicitly; NB-IoT's deep-sleep-optimized modes (eDRX, PSM — Power Saving Mode) are essential to use, not optional, for any cellular-connected battery node with a multi-month life target.

## Key part families

- **SoCs/radios**: Espressif ESP32-class (Wi-Fi+BLE), Nordic nRF52/nRF53-class (BLE/Thread/Zigbee, lowest sleep current), Semtech SX126x-class LoRa transceivers, and NB-IoT/LTE-M cellular modules (e.g., Quectel, u-blox cellular module families).
- **Low-IQ regulators**: ultra-low-quiescent-current LDOs and buck converters (sub-µA to low-µA IQ parts from TI, Analog Devices, and others) purpose-built for battery-node sleep-current budgets.
- **Charge management**: single-cell Li-ion/LiPo linear or switching charger ICs with integrated protection (e.g., TI BQ2407x-class, MCP73831-class) for solar/energy-harvesting nodes.
- **Sensors**: I2C/SPI environmental sensors (temperature/humidity, pressure) and IMUs with hardware wake-on-motion/wake-on-threshold interrupt capability.
- **Antennas**: printed PCB trace antennas, discrete ceramic chip antennas, or u.FL/IPEX external antenna connectors depending on enclosure and range requirements.

## Power tree and battery selection

- **Primary (non-rechargeable) lithium**: CR2032/CR2450-class coin cells for the lowest-power, smallest nodes (BLE-only, infrequent reporting); LiSOCl2 (lithium thionyl chloride) cells for the longest-life, most power-sensitive industrial sensor nodes (very low self-discharge, wide temperature range, but higher cost and a passivation-layer characteristic requiring the load profile to avoid sustained high-current draw without a supercapacitor/hybrid-layer buffer — check the specific cell's datasheet pulse-current guidance).
- **Rechargeable Li-ion/LiPo with energy harvesting**: a single-cell Li-ion/LiPo (nominal 3.7 V) charged from a small solar panel, plus a charge-management IC (linear or switching, see power_battery_bms_ups.md) — appropriate where the deployment location has enough ambient light/energy to sustain the node indefinitely, common in outdoor environmental monitoring.
- **Regulator topology**: most sensor nodes use a low-quiescent-current LDO (sub-µA to low-µA quiescent current parts exist specifically for this application) rather than a switching buck when battery voltage is close to the required logic voltage, since a switcher's own switching losses and typically higher quiescent current can exceed the savings from its better conversion efficiency at the very low average currents these nodes draw — but where the battery voltage is well above the logic rail (e.g., a 2xAA or higher-voltage primary cell down to 3.3V logic) or the node has periodic higher-current bursts (radio TX), an efficient low-IQ buck (many parts now offer sub-1µA quiescent current switching regulators) may still win on average battery life; model both across the actual duty cycle rather than assuming one topology is always better.
- **Sensor power gating**: switch power to sensors (via a small load switch or GPIO-controlled MOSFET) entirely off between readings rather than leaving them powered and relying on the sensor's own low-power/shutdown mode — many low-cost sensors' "shutdown" current is still tens of µA, which can dominate the node's total sleep budget if left enabled continuously; full power removal (when the sensor's settling/warm-up time after power-on is acceptable for the reporting interval) is usually the lower-total-energy choice.

## Sensor interfaces

- Common sensor types: temperature/humidity (I2C, e.g., SHT-family or similar), pressure (I2C/SPI), accelerometer/IMU (I2C/SPI, often itself capable of hardware wake-on-motion interrupts that let the MCU stay asleep until real activity occurs), and analog sensors (soil moisture, light, gas) requiring an ADC channel and often signal conditioning per analog_and_mixed_signal.md.
- **Wake-on-interrupt architecture**: design the sensor interface so the sensor itself (not periodic MCU polling) generates the event that wakes the MCU where possible — an accelerometer's motion-detection interrupt, a comparator-based threshold trigger, or a sensor's own data-ready interrupt all let the MCU spend more of its time in the deepest available sleep state instead of periodically waking just to check "has anything changed."
- I2C bus pull-ups: size pull-up resistors for the bus's actual capacitance and speed, but also consider their contribution to sleep current if the bus is left powered during sleep (a few kΩ pull-up to a rail that stays on during sleep draws continuous current) — gating sensor bus power off during sleep (see above) also removes this leakage path.

## Antenna design

- **PCB trace/inverted-F antenna**: a printed antenna trace (common for BLE 2.4 GHz designs) integrated directly into the PCB edge, eliminating a discrete antenna component's cost and assembly step — requires careful ground-plane keepout beneath and around the antenna trace (per the reference design's exact keepout dimensions from the SoC vendor or antenna IP provider) and a matching network (typically a pi-network of 0402/0201 passives) tuned for the specific board's ground-plane geometry and enclosure material, since a printed antenna's performance is sensitive to nearby ground copper, enclosure plastic, and even battery/component placement.
- **Chip antenna**: a small discrete ceramic antenna component, more forgiving of layout variation than a printed trace antenna, at slightly higher cost and board area — a reasonable default choice for a first design or where board space for a proper printed-antenna keepout isn't available.
- **External antenna via u.FL/IPEX connector**: used when the enclosure material would badly attenuate an internal antenna (metal enclosure, dense equipment rack mounting) or when antenna placement needs to be physically separated from the main board (e.g., mounted outside a metal cabinet) — adds connector cost/board area but removes enclosure-material uncertainty from the antenna design.
- **LoRa/sub-GHz antennas** (868/915 MHz depending on region) are physically larger than 2.4 GHz BLE/Wi-Fi antennas for the same efficiency, often requiring either a larger printed antenna area, a helical/coil discrete antenna, or accepting reduced efficiency in a compact enclosure — plan enclosure size around the antenna requirement early for sub-GHz designs, not as an afterthought.
- Keep switching regulators, crystal oscillators, and any digital clock/bus traces away from the antenna's near-field region and matching network — RF layout guidance in clocks_and_rf_basics.md applies directly; a poorly isolated antenna region can show acceptable bench range but fail in the final enclosure due to coupled noise from nearby digital switching.

## Firmware/hardware co-design for low power

- Real-time clock (RTC) with the lowest-power available oscillator (a 32.768 kHz crystal for the RTC, separate from the higher-frequency main system clock which is only enabled when active) drives the sleep/wake timing — verify the RTC crystal's load capacitance matches the SoC's internal RTC oscillator circuit requirement, a frequently-missed detail that causes RTC timing drift or failure to start reliably.
- Brown-out detection: as a battery discharges (especially non-rechargeable primary cells near end-of-life, or a cold-temperature-derated LiSOCl2 cell under load), voltage droops — configure the SoC's brown-out detector threshold appropriately so the node reports a clear low-battery/fault condition rather than behaving erratically (partial resets, corrupted flash writes) as the battery approaches its cutoff voltage.
- Flash/EEPROM write endurance: if the node logs data locally between transmission windows, consider flash wear leveling or an FRAM-based low-power nonvolatile buffer for frequently-updated data, since standard NOR/NAND flash write endurance (commonly on the order of 10,000–100,000 cycles per sector) can be exhausted well within a multi-year deployment if written naively at high frequency.

## Layer count and stackup

- Most sensor nodes are practically built on 2 or 4 layers — 2 layers is common and acceptable for simple, low-pin-count SoC designs with a modest sensor set, provided the ground-plane and antenna-keepout requirements (which benefit strongly from a solid ground plane, favoring 4 layers) are still met; 4 layers is the safer default once a printed antenna, multiple sensors, or a switching regulator are all present on the same small board, per stackup_and_layer_count.md.

## Placement and routing priorities

1. Antenna keepout region respected exactly per the reference design/vendor guidance — no ground copper, components, or the battery itself within the specified keepout, and enclosure material/mounting considered as part of this decision, not just the bare-board layout.
2. Sensor power-gating switch and sensor bus placed to allow clean, short traces to the sensor's package, with the sleep-current-contributing bus pull-ups sized minimally.
3. Switching regulator (if used) hot loop minimized per power_buck_boost_converters.md, and kept away from the antenna and any analog sensor front end.
4. RTC crystal placed close to the SoC with short, symmetric traces and a solid local ground reference, away from any switching/digital noise source.
5. Battery connector/holder placed and mechanically secured appropriately for the enclosure's expected handling (a coin-cell holder's retention force matters for field-deployed nodes subject to vibration/handling).

## Safety and standards

- Radio certification: any design transmitting RF (BLE, Wi-Fi, LoRa, cellular) needs regulatory certification for the target market (FCC in the US, CE/RED in the EU, and country-specific certifications elsewhere) — using a pre-certified module (rather than a custom RF design) is the standard way small teams avoid the cost/complexity of full modular or full-system RF certification testing; verify the specific module's certification covers the intended end-product configuration (antenna type, enclosure, power level) since modular certification often has conditions attached.
- Battery safety: primary lithium cells (especially LiSOCl2) have specific handling/protection requirements (reverse-polarity protection, avoiding sustained short-circuit or forced-discharge conditions) — follow the cell manufacturer's application guidance; rechargeable Li-ion/LiPo nodes need charge-protection circuitry per power_battery_bms_ups.md even at small single-cell scale.

## Test and bring-up plan

1. Bring up the board on a bench supply first (not battery) to verify basic function, sensor readback, and radio connectivity before evaluating power consumption.
2. Measure actual sleep current with a precision µA-capable meter (many multimeters cannot accurately measure sub-µA currents — a dedicated power profiler, e.g., a Nordic Power Profiler Kit or Joulescope-class instrument, is the right tool) — verify it matches the datasheet-predicted value; a mismatch usually indicates a leakage path (an unintentionally-powered peripheral, a floating GPIO drawing through an internal pull, an antenna-matching component miswired) rather than a bad part.
3. Verify wake-on-interrupt sensor behavior actually wakes the MCU and returns to sleep correctly afterward, not just that it works once — a common bug is failing to correctly clear/re-arm the interrupt, leaving the MCU unable to sleep again.
4. Range/RF test in the actual intended enclosure (not bare board) since enclosure material and internal component placement can significantly affect real-world range versus bare-board bench range.
5. Full duty-cycle battery-life estimate: measure actual current in each state (deep sleep, sensor read, radio TX/RX) and actual time spent in each state per reporting cycle, then calculate expected battery life against the selected cell's capacity — validate this against at least a multi-day real battery discharge test before committing to a claimed battery-life spec.
6. Brown-out/low-battery behavior test: discharge a test battery (or use a bench supply ramped down slowly) through the node's expected end-of-life voltage range and verify the node reports fault status cleanly rather than behaving erratically.

## Common failure modes

- Sleep current far higher than datasheet-predicted due to a leftover powered peripheral, floating input pin, or unaddressed leakage path — the most common single issue in first-revision low-power designs.
- Antenna keepout violated by a component or the battery itself, degrading range significantly versus the bare reference design's performance.
- Polling-based firmware architecture ported from an easier/higher-power platform, failing to realize the target SoC's actual low-power capability.
- RTC crystal load capacitance mismatched to the SoC's oscillator circuit, causing timekeeping drift or unreliable startup.
- Sensor bus pull-ups left powered continuously during sleep, adding a small but real continuous current draw that meaningfully shortens battery life at these current scales.
- Battery-life claim based only on datasheet typical currents without a real multi-day discharge validation, missing real-world effects (temperature, actual duty cycle, cell self-discharge) that datasheet numbers don't capture.

## Schematic review checklist

- [ ] Regulator topology (LDO vs. low-IQ switching buck) chosen based on actual battery-voltage-to-logic-voltage delta and duty cycle, not a default assumption.
- [ ] Sensor power gating (switched, not just sensor-shutdown-mode) implemented where sensor shutdown current is a meaningful fraction of total sleep budget.
- [ ] Wake-on-interrupt sensor capability used where available, rather than MCU-polling architecture.
- [ ] RTC crystal load capacitance matched to the SoC's internal oscillator circuit requirement.
- [ ] Brown-out detection threshold configured appropriately for the selected battery chemistry's end-of-life voltage behavior.
- [ ] Radio module selected is pre-certified for the target regulatory market, with the design's antenna/power configuration within the module's certification conditions.

## Layout review checklist

- [ ] Antenna keepout region respected exactly per vendor reference design, with no ground copper, components, or battery within it.
- [ ] Antenna matching network placed and routed per the reference design's exact topology and trace geometry.
- [ ] Switching regulator hot loop and any digital clock/bus traces kept clear of the antenna near-field region.
- [ ] RTC crystal placed close to the SoC with short, symmetric traces and solid local ground.
- [ ] Sensor bus pull-up values minimized appropriately for sleep-current contribution while meeting bus speed/capacitance requirements.
- [ ] Battery connector/holder mechanically secured appropriately for the deployment's handling/vibration environment.
