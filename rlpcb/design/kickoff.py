"""Project kickoff: from "I want to build X" to a first architecture, the questions to answer, the pitfalls to watch,
and a project structure — before a single part is placed.

An engineer facing a blank schematic usually knows what the product must do but not where to start. The archetypes
below encode the usual starting architecture for common product types: the functional blocks, typical part families,
which blocks RL PCB already has as pre-verified circuits, what to watch for in each, and the questions whose answers
change the design. The model adapts them to the idea; the engineer decides.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

GENERIC_QUESTIONS = [
    "Power source: battery (chemistry, cells, capacity), USB, wall adapter (voltage), mains, or an existing rail?",
    "What does it connect to: sensors, actuators, displays, other boards, a PC, the cloud (Wi-Fi/BLE/Ethernet/cellular)?",
    "Size and shape limits, enclosure, connectors' positions (does the board fit an existing product?)",
    "Environment: indoor/outdoor, temperature range, vibration, water, EMC regulations for the target market",
    "Quantity and manufacturing: prototype by hand, or assembled by JLCPCB/PCBWay; budget per board",
    "Firmware: which MCU family does the team already know? Any existing code to reuse?",
]

ARCHETYPES: Dict[str, Dict] = {
    "iot_sensor_node": {
        "title": "Wireless sensor node (Wi-Fi / BLE)",
        "keywords": "iot wifi wi-fi wireless bluetooth ble esp32 esp sensor node telemetry cloud mqtt home automation "
                    "weather monitor logger",
        "doc": "iot_sensor_node.md",
        "blocks": [
            {"name": "Power input and protection", "sheet": "Power", "function": "USB or battery input, reverse/ESD "
             "protection", "parts": "USB-C receptacle, TVS, P-FET reverse protection", "library": ["usb_c_device"],
             "watch": "Wi-Fi transmit bursts draw 300–500 mA peaks: size the regulator and bulk capacitance for the peak, "
                      "not the average"},
            {"name": "3.3 V regulator", "sheet": "Power", "function": "3.3 V for the radio module and sensors",
             "parts": "LDO (AP2112K, 600 mA) for USB power; buck (TPS62xxx) for battery life", "library": ["ldo_3v3"],
             "watch": "an LDO from a 4.2 V Li-ion cell wastes ~25 %; quiescent current decides standby battery life"},
            {"name": "Radio module", "sheet": "MCU", "function": "Wi-Fi/BLE and the application MCU in one certified "
             "module", "parts": "ESP32-C3/-S3 module (certified), or nRF52840 module for BLE only", "library": [],
             "watch": "keep copper, parts and ground pour out of the antenna keep-out on ALL layers; antenna at the "
                      "board edge, pointing away from metal"},
            {"name": "Sensors", "sheet": "Sensors", "function": "what the node measures", "parts": "I2C sensors (BMP280, "
             "SHT4x, BME680), ADC inputs with dividers", "library": ["bmp280_i2c", "voltage_divider_adc"],
             "watch": "self-heating: keep temperature/humidity sensors away from the regulator and the radio module"},
            {"name": "Programming and debug", "sheet": "MCU", "function": "flash firmware and see logs", "parts": "USB "
             "(native USB on ESP32-S3/C3) or a UART header; BOOT and RESET buttons", "library": ["connector"],
             "watch": "boot-strapping pins have required levels at reset; check the module's strapping table"},
            {"name": "Indicators", "sheet": "MCU", "function": "status LED", "parts": "LED + resistor",
             "library": ["led_indicator"], "watch": "a always-on LED can dominate a battery device's current"},
        ],
        "questions": ["Battery or mains-powered? Target battery life?", "Which radio: Wi-Fi (higher power, direct to "
                      "router), BLE (low power, needs a phone/gateway), LoRa (long range, low data)?",
                      "What is measured, how often, and how accurately?", "Indoor or outdoor enclosure?"],
        "pitfalls": ["Use a pre-certified radio module: a chip-down radio needs RF layout skill and its own "
                     "certification", "Antenna keep-out violations are the most common reason these boards have poor range",
                     "Brown-out during Wi-Fi bursts on weak batteries: add bulk capacitance and test at the lowest battery "
                     "voltage"],
        "layers": "2 layers is usually enough (4 if space is tight); solid ground on the bottom except under the antenna",
    },
    "usb_device": {
        "title": "USB-powered MCU device (USB peripheral, controller, instrument)",
        "keywords": "usb device mcu stm32 rp2040 keyboard controller instrument hid serial adapter gadget macro pad "
                    "midi data acquisition",
        "doc": "microcontroller_and_fpga_boards.md",
        "blocks": [
            {"name": "USB-C port with ESD", "sheet": "USB", "function": "power and data from the host",
             "parts": "USB-C receptacle (USB 2.0), 5.1 kΩ CC resistors, USBLC6 ESD array", "library": ["usb_c_device"],
             "watch": "both CC pins need their own 5.1 kΩ to ground or many chargers will not supply power"},
            {"name": "3.3 V regulator", "sheet": "Power", "function": "logic supply", "parts": "AP2112K-3.3 LDO",
             "library": ["ldo_3v3"], "watch": "total 3.3 V load including LEDs and peripherals vs. the LDO's current and "
                                                "dissipation ((5 − 3.3) V × I)"},
            {"name": "MCU core", "sheet": "MCU", "function": "the application", "parts": "STM32 (F4/G4), RP2040, "
             "ATmega32U4", "library": ["stm32f405_core"], "watch": "decoupling at every VDD pin, the crystal close to "
                                                                   "the MCU, BOOT pins defined at reset"},
            {"name": "I/O", "sheet": "IO", "function": "buttons, LEDs, connectors to the outside", "parts": "JST-SH, "
             "headers, LEDs", "library": ["connector", "led_indicator"], "watch": "series resistors / ESD on every "
                                                                                 "signal that leaves the board"},
        ],
        "questions": ["Bus-powered only, or also an external supply?", "Which MCU does the team know? Is USB "
                      "full-speed (12 Mbit/s) enough?", "What does the device connect to besides USB?"],
        "pitfalls": ["D+/D− routed as a 90 Ω pair, short, with ESD at the connector", "USB-C receptacles with "
                     "SBU/CC confusion: check the pinout against the exact part", "VBUS back-feeding when also powered "
                                                                                  "externally: add an OR-ing diode"],
        "layers": "2 layers fine for USB full-speed; 4 if dense",
    },
    "drone_flight_controller": {
        "title": "Drone flight controller",
        "keywords": "drone quad quadcopter flight controller fc uav betaflight inav ardupilot multirotor fpv",
        "doc": "avionics_and_high_rel_board.md",
        "blocks": [
            {"name": "Battery input and 5 V buck", "sheet": "Power", "function": "2–6S battery to 5 V",
             "parts": "TPS5430 buck, TVS clamp", "library": ["battery_input", "tps5430_buck"],
             "watch": "ESC switching spikes on the battery lead: TVS and a low-ESR bulk capacitor at the input"},
            {"name": "3.3 V LDOs", "sheet": "Power", "function": "clean supply for MCU and a separate one for the IMU",
             "parts": "AP2112K", "library": ["ldo_3v3"], "watch": "the IMU's supply is its noise floor"},
            {"name": "MCU core", "sheet": "MCU", "function": "flight control", "parts": "STM32F405/F722/H743",
             "library": ["stm32f405_core"], "watch": "pin map must match the flight firmware's target definition"},
            {"name": "IMU", "sheet": "Sensors", "function": "gyro + accelerometer on SPI", "parts": "ICM-20602/42688",
             "library": ["icm20602_spi"], "watch": "mount near the board centre, away from the buck; soft-mount the board"},
            {"name": "Barometer and flash", "sheet": "Sensors", "function": "altitude, blackbox logging",
             "parts": "BMP280, W25Q128", "library": ["bmp280_i2c", "w25q_flash_spi"],
             "watch": "cover the barometer from prop wash and light (foam)"},
            {"name": "Connectors", "sheet": "Connectors", "function": "ESC, receiver, VTX, USB",
             "parts": "JST-SH, USB-C", "library": ["connector", "usb_c_device", "voltage_divider_adc"],
             "watch": "ESC connector pinout must match the ESC you buy (RL PCB system_check verifies it)"},
        ],
        "questions": ["Battery cell count (sets the buck's input rating and TVS)", "Board size: 30.5 or 20 mm "
                      "stack?", "Which firmware (Betaflight/INAV/ArduPilot) and which receiver protocol?"],
        "pitfalls": ["Gyro noise from the buck converter: keep them apart and filter the IMU supply",
                     "Mount pattern and connector pinout must match the ESC and the frame"],
        "layers": "4 layers (ground plane under the IMU and MCU)",
    },
    "motor_controller": {
        "title": "Motor controller (stepper / BLDC / brushed)",
        "keywords": "motor driver stepper bldc brushed servo controller cnc 3d printer robot joint actuator h-bridge "
                    "foc gimbal conveyor",
        "doc": "motor_drives_and_motion.md",
        "blocks": [
            {"name": "Power input", "sheet": "Power", "function": "12–48 V motor supply with protection",
             "parts": "TVS, reverse-polarity FET, bulk electrolytics", "library": ["battery_input"],
             "watch": "motor braking pumps energy back into the supply: bulk capacitance and/or a brake resistor"},
            {"name": "Logic supply", "sheet": "Power", "function": "5 V / 3.3 V from the motor rail",
             "parts": "buck (TPS5430 or similar) + LDO", "library": ["tps5430_buck", "ldo_3v3"], "watch": ""},
            {"name": "MCU", "sheet": "MCU", "function": "control loop, communication",
             "parts": "STM32G4 (motor timers, comparators) or F4", "library": ["stm32f405_core"],
             "watch": "use advanced-timer pins with complementary outputs and dead time"},
            {"name": "Power stage", "sheet": "Driver", "function": "drive the motor windings",
             "parts": "integrated driver (TMC2209/DRV8825 steppers, DRV8316 BLDC) or gate driver + MOSFETs",
             "library": [], "watch": "the high-current loop (input cap → MOSFETs → shunt → ground) must be tiny; "
                                     "thermal: copper area and vias under the driver"},
            {"name": "Current sensing", "sheet": "Driver", "function": "per-phase or bus current",
             "parts": "shunt + amplifier (INA240) or driver's built-in sense", "library": [],
             "watch": "Kelvin connections to the shunt; route sense lines as a pair"},
            {"name": "Feedback and I/O", "sheet": "IO", "function": "encoder/hall inputs, limit switches, comms",
             "parts": "connectors, RC filters, CAN transceiver", "library": ["connector"],
             "watch": "filter and protect every input that runs along the machine"},
        ],
        "questions": ["Motor type, voltage, current (continuous/peak)?", "Open loop or closed loop (encoder/halls)?",
                      "How is it commanded: step/dir, UART, CAN, PWM?"],
        "pitfalls": ["Undersized copper for phase currents (use the trace-width calculator)", "Ground bounce from "
                     "the power stage corrupting MCU and sense signals: star-point the power and signal grounds"],
        "layers": "4 layers with 2 oz outer copper for currents above ~5 A",
    },
    "battery_device": {
        "title": "Battery-powered portable device (Li-ion, charging)",
        "keywords": "battery portable wearable li-ion lipo charger charging handheld power bank tracker low power",
        "doc": "power_battery_bms_ups.md",
        "blocks": [
            {"name": "Charger", "sheet": "Power", "function": "charge the cell from USB", "parts": "MCP73831 (simple), "
             "BQ24074 (power-path)", "library": ["usb_c_device"],
             "watch": "a power-path charger lets the device run from USB with a flat battery"},
            {"name": "Protection", "sheet": "Power", "function": "over-discharge, over-current, short", "parts": "DW01 + "
             "FS8205, or a protected cell", "library": [], "watch": "never ship an unprotected Li-ion cell"},
            {"name": "Regulator", "sheet": "Power", "function": "3.3 V from 3.0–4.2 V", "parts": "buck-boost "
             "(TPS63001) or low-dropout LDO", "library": ["ldo_3v3"],
             "watch": "an LDO drops out below ~3.4 V: a third of the cell's capacity is lost"},
            {"name": "MCU / radio", "sheet": "MCU", "function": "application", "parts": "nRF52, ESP32-C3, STM32L4",
             "library": [], "watch": "sleep current: every pull-up and LED counts"},
            {"name": "Battery monitor", "sheet": "Power", "function": "state of charge", "parts": "divider to ADC or "
             "fuel gauge (MAX17048)", "library": ["voltage_divider_adc"],
             "watch": "a divider drains the cell; switch it, or use 1 MΩ values with a filter capacitor"},
        ],
        "questions": ["Cell type and capacity? Target runtime?", "Charging from USB? Must it run while charging?",
                      "Shipping / certification constraints (UN38.3)?"],
        "pitfalls": ["Thermal: charger dissipation inside a sealed case", "Reverse battery insertion with removable "
                     "cells"],
        "layers": "2 or 4 layers",
    },
    "industrial_io": {
        "title": "Industrial controller / PLC I/O (24 V)",
        "keywords": "plc industrial 24v io module relay digital input output 4-20ma modbus rs485 factory automation "
                    "din rail",
        "doc": "plc_controller_and_io_modules.md",
        "blocks": [
            {"name": "24 V input and protection", "sheet": "Power", "function": "field supply with surge protection",
             "parts": "TVS (SMBJ33A), reverse FET, fuse", "library": ["battery_input", "tps5430_buck"],
             "watch": "IEC 61000-4-5 surge on long field wiring"},
            {"name": "Digital inputs", "sheet": "IO", "function": "24 V signals to logic", "parts": "optocouplers or "
             "isolated digital input ICs (ISO1211)", "library": [], "watch": "IEC 61131-2 input type thresholds"},
            {"name": "Outputs", "sheet": "IO", "function": "drive loads", "parts": "high-side switches (VNx), relays",
             "library": [], "watch": "inductive kickback: flyback clamps on every inductive load"},
            {"name": "Fieldbus", "sheet": "Comms", "function": "Modbus RTU / CAN", "parts": "isolated RS-485 "
             "transceiver", "library": [], "watch": "termination and biasing; isolation barrier creepage"},
            {"name": "MCU", "sheet": "MCU", "function": "logic", "parts": "STM32", "library": ["stm32f405_core"],
             "watch": "watchdog and safe output state at reset"},
        ],
        "questions": ["How many inputs/outputs, what type (sink/source, analog 4–20 mA)?", "Isolation required?",
                      "Fieldbus?"],
        "pitfalls": ["Creepage/clearance across isolation barriers", "Outputs must default to off on reset and "
                     "brown-out"],
        "layers": "4 layers",
    },
    "printer_system": {
        "title": "Printer (multi-board system: formatter, engine controller, motor drivers, power, panel)",
        "keywords": "printer laser inkjet thermal receipt kyocera print engine fuser paper feed toner copier mfp "
                    "label printer",
        "doc": "printer_mainboard_kyocera_class.md",
        "boards": ["formatter (job handling, network, UI)", "engine controller (real-time: motors, sensors, fuser, HVPS "
                   "sequencing)", "motor driver board(s)", "power supply (AC-DC, standby converter)", "control panel"],
        "blocks": [
            {"name": "Engine controller MCU", "sheet": "MCU", "function": "real-time control of the print engine",
             "parts": "STM32-class MCU", "library": ["stm32f405_core"],
             "watch": "hardware interlocks must cut fuser and HVPS power without firmware"},
            {"name": "Motor drivers", "sheet": "Motors", "function": "paper feed, drum, developer motors",
             "parts": "stepper drivers (TMC2209), BLDC driver for the polygon/drum", "library": [],
             "watch": "see the motor-controller archetype"},
            {"name": "Paper-path sensors", "sheet": "IO", "function": "jam, paper present, door open",
             "parts": "optical interrupters, microswitches", "library": ["connector"],
             "watch": "debounce and filter; long cable runs need protection"},
            {"name": "Print head / heater control", "sheet": "Power", "function": "thermal head (receipt printer) or "
             "fuser heater (laser)", "parts": "thermal head driver; for a fuser: zero-cross TRIAC with thermal fuse",
             "library": [], "watch": "MAINS: fuser control is safety-critical (IEC 62368-1); a thermal printer is the "
                                     "sensible first project"},
            {"name": "Host interface", "sheet": "Comms", "function": "USB / Ethernet / Wi-Fi", "parts": "USB-C, "
             "ESP32 module", "library": ["usb_c_device"], "watch": ""},
            {"name": "Power", "sheet": "Power", "function": "24 V motors, 5/3.3 V logic", "parts": "24 V adapter or "
             "AC-DC module + buck + LDO", "library": ["tps5430_buck", "ldo_3v3"],
             "watch": "use a certified AC-DC module rather than designing the mains stage"},
        ],
        "questions": ["Which printing technology: thermal (receipt/label), inkjet, or laser? (laser adds mains "
                      "fuser and kilovolt HVPS)", "Paper width and speed?", "Which board first? (start with the engine "
                                                                                     "controller on a bench)"],
        "pitfalls": ["Starting with the mains/HVPS parts: begin with a thermal printer or the low-voltage engine "
                     "controller", "Each board is its own project: define the cables between them first "
                                     "(RL PCB system_create / system_add_harness)"],
        "layers": "engine controller 4 layers; power boards 2 layers with 2 oz copper",
    },
    "power_supply": {
        "title": "Power supply / converter module",
        "keywords": "power supply buck boost converter regulator bench supply dc-dc psu charger module voltage",
        "doc": "power_buck_boost_converters.md",
        "blocks": [
            {"name": "Input protection", "sheet": "Power", "function": "reverse polarity, surge, inrush",
             "parts": "TVS, P-FET or ideal diode, fuse", "library": ["battery_input"], "watch": ""},
            {"name": "Converter", "sheet": "Power", "function": "the conversion", "parts": "TPS5430 (3 A buck), "
             "TPS61088 (boost), LM5176 (buck-boost)", "library": ["tps5430_buck"],
             "watch": "the hot loop layout decides whether it works; follow the datasheet layout exactly"},
            {"name": "Output and monitoring", "sheet": "Power", "function": "output caps, voltage/current sense",
             "parts": "ceramic + polymer caps, INA219/226", "library": ["voltage_divider_adc"],
             "watch": "ceramic capacitors lose capacitance with DC bias: check the curve at the output voltage"},
        ],
        "questions": ["Input range, output voltage(s), current, efficiency target?", "Isolated or not?"],
        "pitfalls": ["Inductor saturation current below the peak", "Feedback trace routed near the switch node"],
        "layers": "2 layers with a solid ground; 4 for higher currents",
    },
}


def _words(s: str) -> List[str]:
    return re.findall(r"[a-z0-9+\-]+", (s or "").lower())


def match(idea: str) -> List[Dict]:
    w = set(_words(idea))
    out = []
    for aid, a in ARCHETYPES.items():
        kw = set(_words(a["keywords"]))
        hits = sorted(w & kw)
        score = len(hits) + sum(1 for x in w if len(x) > 4 and any(x in k or k in x for k in kw if len(k) > 4)) * 0.3
        if score:
            out.append({"id": aid, "title": a["title"], "score": round(score, 2), "matched": hits})
    out.sort(key=lambda r: -r["score"])
    return out


def brief(idea: str, archetype: str = "") -> Dict:
    """A kickoff brief for the idea: architecture, pre-verified blocks available, questions, pitfalls, structure."""
    ranked = match(idea)
    aid = archetype or (ranked[0]["id"] if ranked else "")
    if aid and aid not in ARCHETYPES:
        raise ValueError(f"unknown archetype {aid}; known: {', '.join(ARCHETYPES)}")
    if not aid:
        return {"idea": idea, "archetype": None, "candidates": [], "questions": GENERIC_QUESTIONS,
                "known_archetypes": {k: v["title"] for k, v in ARCHETYPES.items()},
                "how": "no archetype matched; ask the questions, then build the architecture from the generic blocks: "
                       "power input → regulators → MCU → interfaces → protection → debug. Use search_knowledge for each"}
    a = ARCHETYPES[aid]
    sheets = []
    for b in a["blocks"]:
        if b["sheet"] not in sheets:
            sheets.append(b["sheet"])
    lib = sorted({x for b in a["blocks"] for x in b.get("library", [])})
    return {
        "idea": idea, "archetype": aid, "title": a["title"], "candidates": ranked[:4],
        "architecture": [{k: b.get(k) for k in ("name", "function", "parts", "watch", "sheet")} | {
            "pre_verified_blocks": b.get("library", []),
            "needs_part_selection": not b.get("library")} for b in a["blocks"]],
        "boards": a.get("boards"),
        "questions": a["questions"] + [q for q in GENERIC_QUESTIONS if q.split(":")[0] not in " ".join(a["questions"])][:3],
        "pitfalls": a["pitfalls"], "layers": a["layers"],
        "read_more": {"tool": "read_guide", "args": {"name": a["doc"]}},
        "structure": {
            "folders": ["<name>/ (KiCad project)", "<name>/datasheets/", "<name>/docs/ (requirements.md, "
                        "decisions.md)", "<name>/fab/ (made at export)"],
            "sheets": sheets,
            "plan_blocks": [b["name"] for b in a["blocks"]],
            "rl_pcb_blocks_available": lib,
        },
        "next": "Discuss the questions with the engineer. When the architecture is agreed, kickoff_apply creates the "
                "project, one sheet per group, the plan's blocks and requirements, and the docs. Then fill each block "
                "with add_block (pre-verified) or part selection.",
    }


def apply(folder: str, name: str, archetype: str, requirements: Optional[Dict] = None, idea: str = "",
          blocks: Optional[List[str]] = None) -> Dict:
    """Create the project from a kickoff brief (called through the tool, so the copilot mode applies)."""
    from .plan import DesignPlan, PlanBlock
    from .project import add_sheet, create_project
    a = ARCHETYPES.get(archetype)
    if not a:
        raise ValueError(f"unknown archetype {archetype}; known: {', '.join(ARCHETYPES)}")
    chosen = [b for b in a["blocks"] if not blocks or b["name"] in blocks]
    r = create_project(folder, name, title=a["title"])
    if "error" in r:
        return r
    pdir = r["folder"]
    sheets = []
    for b in chosen:
        if b["sheet"] not in sheets:
            sheets.append(b["sheet"])
    made = []
    for sh in sheets:
        made.append(add_sheet(r["schematic"], sh).get("child", sh))
    plan = DesignPlan(name=name, description=idea or a["title"])
    for b in chosen:
        bid = re.sub(r"[^a-z0-9]+", "_", b["name"].lower()).strip("_")
        plan.blocks.append(PlanBlock(id=bid, title=b["name"], purpose=b["function"],
                                     notes=f"Typical parts: {b['parts']}. Watch: {b['watch']}".strip(),
                                     reference_design=", ".join(b.get("library", []))))
    plan.requirements = dict(requirements or {})
    plan.decisions.append(f"Kickoff: started from the '{a['title']}' archetype")
    plan.save(pdir)
    os.makedirs(os.path.join(pdir, "datasheets"), exist_ok=True)
    os.makedirs(os.path.join(pdir, "docs"), exist_ok=True)
    with open(os.path.join(pdir, "docs", "requirements.md"), "w", encoding="utf-8") as f:
        f.write(f"# {name}: requirements\n\n{idea}\n\n## Answers so far\n\n")
        for k, v in (requirements or {}).items():
            f.write(f"- **{k}**: {v}\n")
        f.write("\n## Open questions\n\n" + "".join(f"- [ ] {q}\n" for q in a["questions"]))
        f.write("\n## Pitfalls to watch\n\n" + "".join(f"- {q}\n" for q in a["pitfalls"]))
    with open(os.path.join(pdir, "docs", "decisions.md"), "w", encoding="utf-8") as f:
        f.write(f"# {name}: design decisions\n\nOne line per decision, with the reason. RL PCB also keeps them in the "
                f"plan (plan_set_info decision=...).\n\n- Started from the '{a['title']}' architecture.\n")
    return {"project": r["project"], "folder": pdir, "sheets": made, "plan_blocks": [b.id for b in plan.blocks],
            "docs": ["docs/requirements.md", "docs/decisions.md"],
            "next": "open the project in KiCad; then for each plan block: add_block (pre-verified) or choose parts"}
