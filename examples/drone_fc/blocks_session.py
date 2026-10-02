"""The drone flight controller again, built from pre-verified blocks: 14 add_block calls instead of ~60 part and
net calls, and no pin numbers anywhere except the connector pinouts.

    python examples/drone_fc/blocks_session.py <parent-folder> [--labels]
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
    elif isinstance(r, dict) and r.get("problems"):
        print(f"!! {_tool} {a.get('instance', '')}: {r['problems']}")
    return r


T("create_project", folder=parent, name="rl_fc_blocks", paper="A3", title="RL-FC F405 (from blocks)")
B = lambda block, inst, params=None, **connect: T("add_block", block=block, instance=inst, params=params or {}, connect=connect)

B("battery_input", "batt", {"vmax": 25.2}, VBAT="VBAT")
B("tps5430_buck", "buck5v", {"vin_min": 7.0, "vin_max": 25.2, "vout": 5.0, "iout": 2.0}, VIN="VBAT", VOUT="+5V")
B("ldo_3v3", "ldo", {"vin_max": 5.25, "iout": 0.4}, VIN="+5V", VOUT="+3V3")
B("voltage_divider_adc", "vbat_sense", {"vmax": 25.2}, IN="VBAT", OUT="VBAT_SENSE")
B("stm32f405_core", "mcu", {"hse_mhz": 8, "crystal_cl_pf": 12}, VDD="+3V3",
  SPI1_SCK="IMU_SCK", SPI1_MISO="IMU_MISO", SPI1_MOSI="IMU_MOSI", PA4="IMU_CS", PC4="IMU_INT",
  I2C1_SCL="I2C_SCL", I2C1_SDA="I2C_SDA",
  SPI3_SCK="FLASH_SCK", SPI3_MISO="FLASH_MISO", SPI3_MOSI="FLASH_MOSI", PB3="FLASH_CS",
  USB_DP="USB_DP", USB_DM="USB_DM", ADC_IN12="VBAT_SENSE", ADC_IN11="ESC_CURR", USART6_RX="ESC_TLM",
  TIM3_CH3="MOTOR1", TIM3_CH4="MOTOR2", TIM5_CH4="MOTOR3", TIM5_CH3="MOTOR4",
  USART1_TX="RX_TX", USART1_RX="RX_RX", USART3_TX="VTX_TX", USART3_RX="VTX_RX",
  SWDIO="SWDIO", SWCLK="SWCLK", PB5="LED_STATUS")
B("icm20602_spi", "imu", None, VDD="+3V3", SCK="IMU_SCK", MOSI="IMU_MOSI", MISO="IMU_MISO", CS="IMU_CS", INT="IMU_INT")
B("bmp280_i2c", "baro", {"address": "0x76", "pullups": True}, VDD="+3V3", SCL="I2C_SCL", SDA="I2C_SDA")
B("w25q_flash_spi", "flash", None, VCC="+3V3", SCK="FLASH_SCK", MOSI="FLASH_MOSI", MISO="FLASH_MISO", CS="FLASH_CS")
B("usb_c_device", "usb", {"vbus_diode": True}, DP="USB_DP", DM="USB_DM", VOUT="+5V")
B("led_indicator", "led_status", {"color": "blue"}, IN="LED_STATUS")
B("led_indicator", "led_power", {"color": "green"}, IN="+3V3")
B("connector", "esc", {"pins": 8, "label": "ESC"}, **{"1": "VBAT", "2": "GND", "3": "ESC_CURR", "4": "ESC_TLM",
                                                      "5": "MOTOR1", "6": "MOTOR2", "7": "MOTOR3", "8": "MOTOR4"})
B("connector", "rx", {"pins": 4, "label": "RX"}, **{"1": "+5V", "2": "GND", "3": "RX_TX", "4": "RX_RX"})
B("connector", "vtx", {"pins": 4, "label": "VTX"}, **{"1": "+5V", "2": "GND", "3": "VTX_TX", "4": "VTX_RX"})
B("connector", "swd", {"pins": 4, "family": "header_1.27", "label": "SWD"}, **{"1": "+3V3", "2": "SWDIO", "3": "SWCLK", "4": "GND"})

rv = T("plan_review")
print(json.dumps({k: rv[k] for k in ("summary", "errors", "warnings")}, indent=1)[:3000])
labels = "--labels" in sys.argv
sheets = {"power": ["batt", "buck5v", "ldo", "vbat_sense"], "mcu": ["mcu", "led_status", "led_power"],
          "sensors": ["imu", "baro", "flash"], "connectors": ["usb", "esc", "rx", "vtx", "swd"]}
for i, (sheet, insts) in enumerate(sheets.items()):
    sh = T("add_sheet", name=sheet.capitalize())
    for inst in insts:
        T("place_parts", block=inst, mode="file", sheet_file=sh["file"], labels=labels)
v = T("verify_schematic")
print(f"verify: {v['progress_percent']} % of {v['connections_planned']} connections; errors: {len(v['errors'])}")
