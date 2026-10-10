"""Worked example: RL PCB designs a 30.5x30.5 mm drone flight controller (STM32F405, ICM-20602, BMP280,
128 Mbit blackbox flash, 2-6S input, 5 V/2 A buck, USB-C). 

    python examples/drone_fc/design_session.py <parent-folder>
"""
import json
import sys

from rlpcb.agent.tools import Session, run_tool

parent = sys.argv[1] if len(sys.argv) > 1 else "."
s = Session()


def T(_tool, **a):
    r = run_tool(s, _tool, a)
    if isinstance(r, dict) and r.get("error"):
        print(f"!! {_tool}: {r['error']}")
    return r


T("create_project", folder=parent, name="rl_fc_f405", paper="A3", title="RL-FC F405 flight controller")
T("plan_set_info", name="RL-FC F405", description="5-inch quad flight controller, Betaflight-compatible pinout",
  requirements={"input": "2S-6S LiPo (7.0-25.2 V), 6S transients to 30 V", "rails": "5 V 2 A (receiver, VTX, camera), 3.3 V 600 mA",
                "form_factor": "36x36 mm, 30.5x30.5 mm M3 mounting", "sensors": "6-axis IMU on SPI, barometer on I2C",
                "logging": "128 Mbit SPI flash (blackbox)", "outputs": "4 DShot motor outputs, ESC current + telemetry",
                "io": "USB-C (config), UART1 receiver, UART3 VTX, SWD", "fab": "JLCPCB 4-layer 1.6 mm"},
  decision="STM32F405RGT6: the reference MCU of Betaflight/INAV (168 MHz FPU, 3 SPI, 6 UART, USB FS); huge ecosystem")
T("plan_set_info", decision="Power: TPS5430 buck (5.5-36 V in, 3 A, 500 kHz) for 5 V, then AP2112K-3.3 LDO: low-noise 3.3 V for MCU + IMU")
T("plan_set_info", decision="IMU on its own ferrite-filtered 3.3 V branch and SPI1 at up to 10 MHz; baro on I2C1 (PB8/PB9) away from the buck")
T("plan_set_info", decision="4-layer stack (SIG / GND / PWR / SIG): solid ground under the MCU/IMU and short return paths for the 500 kHz buck")

for b in [("power", "Power: 2-6S input, 5 V buck, 3.3 V LDO, battery sensing", "Buck hot loop (VIN cap - U1 - D1) as small as possible, far from the IMU"),
          ("mcu", "STM32F405 core: decoupling, clock, reset, boot, SWD, USB", "Crystal + caps within 5 mm of PH0/PH1; VCAP caps at the pins"),
          ("sensors", "IMU (SPI1), barometer (I2C1), blackbox flash (SPI3)", "IMU at the board centre, away from motor/ESC wiring and the buck inductor"),
          ("io", "ESC / receiver / VTX / USB connectors and LEDs", "Connectors on the board edges; USB ESD part right at the connector")]:
    T("plan_add_block", id=b[0], title=b[1], layout_notes=b[2])

C = lambda ref, lib, val="", fp="", block="", role="", **f: {"ref": ref, "lib_id": lib, "value": val, "footprint": fp, "block": block, "role": role, "fields": f}
R0402, C0402, C0603, C0805 = "Resistor_SMD:R_0402_1005Metric", "Capacitor_SMD:C_0402_1005Metric", "Capacitor_SMD:C_0603_1608Metric", "Capacitor_SMD:C_0805_2012Metric"
parts = [
    # ---------------- power
    C("J1", "Connector_Generic:Conn_01x02", "BATT", "Connector_Wire:SolderWire-1.5sqmm_1x02_P6mm_D1.7mm_OD3mm", "power", "Battery pads (VBAT, GND)"),
    C("D2", "Diode:SMAJ28A", "SMAJ28A", "Diode_SMD:D_SMA", "power", "TVS: clamps ESC/motor spikes on VBAT (28 V standoff > 25.2 V 6S)"),
    C("C1", "Device:C", "10u 50V", "Capacitor_SMD:C_1206_3216Metric", "power", "Buck input cap (X7R) - hot loop"),
    C("C2", "Device:C", "10u 50V", "Capacitor_SMD:C_1206_3216Metric", "power", "Buck input cap (X7R)"),
    C("U1", "Regulator_Switching:TPS5430DDA", "TPS5430", "", "power", "5 V / 3 A buck, 500 kHz"),
    C("C3", "Device:C", "10n", C0402, "power", "Bootstrap cap BOOT-PH"),
    C("D1", "Diode:B340", "B340A", "Diode_SMD:D_SMA", "power", "Catch diode (40 V 3 A Schottky)"),
    C("L1", "Device:L", "15u", "Inductor_SMD:L_Bourns_SRP7028A_7.3x6.6mm", "power", "Buck inductor (calc 13.4 uH, Isat > 3 A; SRP7028A-150M size, 7.3x6.6 mm, chosen to fit the 36 mm board; confirm Isat in datasheet)"),
    C("C4", "Device:C", "22u 10V", C0805, "power", "Buck output cap"),
    C("C5", "Device:C", "22u 10V", C0805, "power", "Buck output cap"),
    C("R1", "Device:R", "9.31k", R0402, "power", "FB top: Vout = 1.221*(1+9.31/3.01) = 4.998 V"),
    C("R2", "Device:R", "3.01k", R0402, "power", "FB bottom"),
    C("U2", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3", "", "power", "3.3 V 600 mA LDO"),
    C("C6", "Device:C", "1u", C0402, "power", "LDO input"),
    C("C7", "Device:C", "4.7u", C0603, "power", "LDO output / 3.3 V bulk"),
    C("R3", "Device:R", "10k", R0402, "power", "VBAT divider top (25.2 V -> 2.29 V)"),
    C("R4", "Device:R", "1k", R0402, "power", "VBAT divider bottom"),
    C("C8", "Device:C", "100n", C0402, "power", "VBAT ADC filter"),
    # ---------------- MCU
    C("U3", "MCU_ST_STM32F4:STM32F405RGTx", "STM32F405RGT6", "", "mcu", "Flight MCU"),
    C("C10", "Device:C", "100n", C0402, "mcu", "VDD pin 19 decoupling"),
    C("C11", "Device:C", "100n", C0402, "mcu", "VDD pin 32 decoupling"),
    C("C12", "Device:C", "100n", C0402, "mcu", "VDD pin 48 decoupling"),
    C("C13", "Device:C", "100n", C0402, "mcu", "VDD pin 64 decoupling"),
    C("C14", "Device:C", "4.7u", C0603, "mcu", "MCU bulk"),
    C("C15", "Device:C", "2.2u", C0402, "mcu", "VCAP_1 (low-ESR, required by the internal regulator)"),
    C("C16", "Device:C", "2.2u", C0402, "mcu", "VCAP_2"),
    C("FB1", "Device:FerriteBead_Small", "600R@100MHz", "Inductor_SMD:L_0603_1608Metric", "mcu", "VDDA filter"),
    C("C17", "Device:C", "1u", C0402, "mcu", "VDDA bulk"),
    C("C18", "Device:C", "100n", C0402, "mcu", "VDDA HF"),
    C("Y1", "Device:Crystal_GND24", "8MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", "mcu", "HSE 8 MHz, CL 12 pF"),
    C("C19", "Device:C", "18p", C0402, "mcu", "Crystal load (2*(12-3) pF)"),
    C("C20", "Device:C", "18p", C0402, "mcu", "Crystal load"),
    C("C21", "Device:C", "100n", C0402, "mcu", "NRST filter"),
    C("R5", "Device:R", "10k", R0402, "mcu", "BOOT0 pull-down (run from flash)"),
    C("SW1", "Switch:SW_Push", "BOOT", "Button_Switch_SMD:SW_SPST_TL3342", "mcu", "Hold at power-up for DFU bootloader"),
    C("D3", "Device:LED", "blue", "LED_SMD:LED_0603_1608Metric", "mcu", "Status LED (PB5)"),
    C("R6", "Device:R", "1k", R0402, "mcu", "Status LED resistor"),
    C("D4", "Device:LED", "green", "LED_SMD:LED_0603_1608Metric", "mcu", "3.3 V power LED"),
    C("R7", "Device:R", "1k", R0402, "mcu", "Power LED resistor"),
    # ---------------- sensors
    C("U4", "Sensor_Motion:ICM-20602", "ICM-20602", "", "sensors", "6-axis IMU (SPI1)"),
    C("FB2", "Device:FerriteBead_Small", "600R@100MHz", "Inductor_SMD:L_0603_1608Metric", "sensors", "Isolates IMU supply from digital noise"),
    C("C22", "Device:C", "100n", C0402, "sensors", "IMU VDD"),
    C("C23", "Device:C", "100n", C0402, "sensors", "IMU VDDIO"),
    C("C24", "Device:C", "100n", C0402, "sensors", "IMU REGOUT (per datasheet)"),
    C("C25", "Device:C", "2.2u", C0402, "sensors", "IMU branch bulk"),
    C("U5", "Sensor_Pressure:BMP280", "BMP280", "", "sensors", "Barometer (I2C addr 0x76)"),
    C("C26", "Device:C", "100n", C0402, "sensors", "Baro decoupling"),
    C("R8", "Device:R", "4.7k", R0402, "sensors", "I2C SCL pull-up"),
    C("R9", "Device:R", "4.7k", R0402, "sensors", "I2C SDA pull-up"),
    C("U6", "Memory_Flash:W25Q128JVS", "W25Q128JV", "", "sensors", "Blackbox flash (SPI3)"),
    C("C27", "Device:C", "100n", C0402, "sensors", "Flash decoupling"),
    C("R10", "Device:R", "10k", R0402, "sensors", "Flash CS pull-up (deselected during boot)"),
    # ---------------- IO
    C("J2", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C", "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal", "io", "Configuration / DFU"),
    C("R11", "Device:R", "5.1k", R0402, "io", "CC1 pull-down (device)"),
    C("R12", "Device:R", "5.1k", R0402, "io", "CC2 pull-down (device)"),
    C("U7", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "", "io", "USB ESD protection"),
    C("D5", "Diode:SS34", "SS34", "Diode_SMD:D_SMA", "io", "VBUS -> 5 V OR-ing (USB power without battery)"),
    C("J3", "Connector_Generic:Conn_01x08", "ESC", "Connector_JST:JST_SH_SM08B-SRSS-TB_1x08-1MP_P1.00mm_Horizontal", "io", "4-in-1 ESC: VBAT GND CUR TLM M1-M4"),
    C("J4", "Connector_Generic:Conn_01x04", "RX", "Connector_JST:JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal", "io", "Receiver (UART1)"),
    C("J5", "Connector_Generic:Conn_01x04", "VTX", "Connector_JST:JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal", "io", "Video transmitter (UART3)"),
    C("J6", "Connector_Generic:Conn_01x04", "SWD", "Connector_PinHeader_1.27mm:PinHeader_1x04_P1.27mm_Vertical", "io", "Debug"),
]
print(json.dumps(T("plan_add_components", components=parts)["problems"], indent=1))

def N(net, pins, **k):
    r = T("plan_connect", net=net, pins=pins, **k)
    for e in r.get("errors", []):
        print(f"!! {net}: {e[:160]}")
    return r
# power
N("VBAT", ["J1.1", "D2.1", "C1.1", "C2.1", "U1.VIN", "R3.1", "J3.1"], net_class="power", current_a=3, voltage_v=25.2)
N("GND", ["J1.2", "D2.2", "C1.2", "C2.2", "U1.GND", "U1.GNDPAD", "D1.A", "C4.2", "C5.2", "R2.2", "U2.GND", "C6.2", "C7.2", "R4.2",
          "C8.2", "U3.VSS", "U3.VSSA", "C10.2", "C11.2", "C12.2", "C13.2", "C14.2", "C15.2", "C16.2", "C17.2", "C18.2",
          "Y1.2", "Y1.4", "C19.2", "C20.2", "C21.2", "R5.2", "D3.K", "D4.K", "U4.GND", "U4.FSYNC", "C22.2", "C23.2",
          "C24.2", "C25.2", "U5.GND", "U5.SDO", "C26.2", "U6.GND", "C27.2", "J2.GND", "J2.SHIELD", "R11.2", "R12.2",
          "U7.GND", "J3.2", "J4.2", "J5.2", "J6.4"], net_class="ground")
N("BUCK_SW", ["U1.PH", "D1.K", "L1.1", "C3.2"], notes="Switch node: short and fat, keep away from IMU and crystal", current_a=2.5)
N("BUCK_BOOT", ["U1.BOOT", "C3.1"])
N("BUCK_FB", ["U1.VSENSE", "R1.2", "R2.1"], notes="Route FB away from the switch node; R1/R2 next to U1")
N("+5V", ["L1.2", "C4.1", "C5.1", "R1.1", "U2.VIN", "U2.EN", "C6.1", "D5.K", "J4.1", "J5.1"], net_class="power", current_a=2)
N("+3V3", ["U2.VOUT", "C7.1", "U3.VDD", "U3.VBAT", "C10.1", "C11.1", "C12.1", "C13.1", "C14.1", "FB1.1", "R7.1", "SW1.2",
           "FB2.1", "U5.VDD", "U5.VDDIO", "U5.CSB", "C26.1", "R8.1", "R9.1", "U6.VCC", "U6.IO2", "U6.IO3", "C27.1", "R10.1", "J6.1"],
  net_class="power", current_a=0.4)
N("VBAT_SENSE", ["R3.2", "R4.1", "C8.1", "U3.PC2"], net_class="analog")
# MCU core
N("VCAP1", ["U3.VCAP_1", "C15.1"]); N("VCAP2", ["U3.VCAP_2", "C16.1"])
N("+3V3A", ["FB1.2", "U3.VDDA", "C17.1", "C18.1"], net_class="analog")
N("OSC_IN", ["U3.PH0", "Y1.1", "C19.1"]); N("OSC_OUT", ["U3.PH1", "Y1.3", "C20.1"])
N("NRST", ["U3.NRST", "C21.1"]); N("BOOT0", ["U3.BOOT0", "R5.1", "SW1.1"])
N("LED_STATUS", ["U3.PB5", "R6.1"]); N("LED_STATUS_K", ["R6.2", "D3.A"]); N("LED_PWR", ["R7.2", "D4.A"])
N("SWDIO", ["U3.PA13", "J6.2"]); N("SWCLK", ["U3.PA14", "J6.3"])
# sensors
N("+3V3_IMU", ["FB2.2", "U4.VDD", "U4.VDDIO", "C22.1", "C23.1", "C25.1"], net_class="analog")
N("IMU_REGOUT", ["U4.REGOUT", "C24.1"])
N("SPI1_SCK", ["U3.PA5", "U4.SCL/SPC"], net_class="high_speed"); N("SPI1_MOSI", ["U3.PA7", "U4.SDA/SDI"], net_class="high_speed")
N("SPI1_MISO", ["U3.PA6", "U4.SAO/SD0"], net_class="high_speed"); N("IMU_CS", ["U3.PA4", "U4.CS"]); N("IMU_INT", ["U3.PC4", "U4.INT"])
N("I2C1_SCL", ["U3.PB8", "U5.SCK", "R8.2"]); N("I2C1_SDA", ["U3.PB9", "U5.SDI", "R9.2"])
N("SPI3_SCK", ["U3.PC10", "U6.CLK"]); N("SPI3_MISO", ["U3.PC11", "U6.DO(IO1)"]); N("SPI3_MOSI", ["U3.PC12", "U6.DI(IO0)"])
N("FLASH_CS", ["U3.PB3", "U6.CS", "R10.2"])
# IO
N("VBUS", ["J2.VBUS", "U7.VBUS", "D5.A"], net_class="power")
N("USB_CC1", ["J2.CC1", "R11.1"]); N("USB_CC2", ["J2.CC2", "R12.1"])
N("USB_CONN_DP", ["J2.D+", "U7.1"], net_class="diff_pair", impedance_ohm=90, diff_partner="USB_CONN_DM")
N("USB_CONN_DM", ["J2.D-", "U7.3"], net_class="diff_pair", impedance_ohm=90, diff_partner="USB_CONN_DP")
N("USB_DP", ["U7.6", "U3.PA12"], net_class="diff_pair", impedance_ohm=90, diff_partner="USB_DM")
N("USB_DM", ["U7.4", "U3.PA11"], net_class="diff_pair", impedance_ohm=90, diff_partner="USB_DP")
N("ESC_CURR", ["J3.3", "U3.PC1"], net_class="analog"); N("ESC_TLM", ["J3.4", "U3.PC7"])
N("MOTOR1", ["J3.5", "U3.PB0"]); N("MOTOR2", ["J3.6", "U3.PB1"]); N("MOTOR3", ["J3.7", "U3.PA3"]); N("MOTOR4", ["J3.8", "U3.PA2"])
N("UART1_TX", ["U3.PA9", "J4.3"]); N("UART1_RX", ["U3.PA10", "J4.4"])
N("UART3_TX", ["U3.PB10", "J5.3"]); N("UART3_RX", ["U3.PB11", "J5.4"])
T("plan_no_connect", pins=["U1.NC", "U1.EN", "U2.NC", "U4.RESV", "J2.SBU1", "J2.SBU2"])
# unused MCU GPIOs
used = {n for net in s.plan().nets for n in net.nodes}
spare = [f"U3.{p['number']}" for p in s.pins_of("MCU_ST_STM32F4:STM32F405RGTx") if f"U3.{p['number']}" not in used and p["type"] != "power_in"]
T("plan_no_connect", pins=spare)
print(json.dumps(T("plan_review"), indent=1)[:3000])

# ---------------- one hierarchical sheet per block, parts placed around the pins they serve (no wires)
LABELS = "--labels" in sys.argv  # demo only: simulate a finished drawing with on-pin labels
for block, sheet in [("power", "Power"), ("mcu", "MCU"), ("sensors", "Sensors"), ("io", "Connectors")]:
    r = T("add_sheet", name=sheet)
    r = T("place_parts", block=block, mode="file", sheet_file=sheet.lower() + ".kicad_sch", labels=LABELS)
    print(f"{sheet}: placed {len(r.get('placed', []))} symbols")
g = T("wiring_guide", block="power")
for n in g["nets"]:
    print(f"- {n['net']} [{n['method']}]")
    for st in n.get("steps", []):
        print("    ", st["step"])
    if n.get("pins"):
        print("    ", n["instruction"][:90], "…", "; ".join(n["pins"][:4]))
v = T("verify_schematic")
print("verify:", v["progress_percent"], "% of", v["connections_planned"], "connections; errors:", len(v["errors"]))
