import os

import pytest

from rlpcb.agent.tools import Session, run_tool
from rlpcb.design.blocks import BLOCKS, list_blocks

LIB = os.path.join(os.environ.get("RLPCB_HOME") or os.path.join(os.path.expanduser("~"), ".rlpcb"), "library_index.db")


def test_every_block_builds_with_defaults():
    for b in list_blocks():
        assert "error" not in b["ports"], (b["id"], b["ports"])


def test_block_parameter_guards():
    with pytest.raises(ValueError):
        BLOCKS["tps5430_buck"].build(vin_min=5.0, vin_max=40)
    with pytest.raises(ValueError):
        BLOCKS["tps5430_buck"].build(vin_min=6.0, vin_max=12, vout=5.9)  # above max duty cycle
    with pytest.raises(ValueError):
        BLOCKS["ldo_3v3"].build(vin_max=12)


def test_buck_values_follow_formulas():
    b = BLOCKS["tps5430_buck"].build(vin_min=7, vin_max=25.2, vout=5.0, iout=2)
    fb = b.calculations[0]["feedback_divider"]
    assert abs(fb["actual_output_v"] - 5.0) < 0.05
    parts = {p["key"]: p for p in b.parts}
    assert parts["CIN1"]["fields"]["Voltage"] == "50V"  # 1.5 × 25.2 V → 50 V rating


def _project(tmp_path):
    s = Session()
    run_tool(s, "create_project", {"folder": str(tmp_path), "name": "b"})
    return s


@pytest.mark.skipif(not os.path.exists(LIB), reason="library index not built")
def test_mcu_function_ports_and_conflicts(tmp_path, rlhome):
    s = _project(tmp_path)
    bad = run_tool(s, "add_block", {"block": "stm32f405_core", "instance": "mcu",
                                    "connect": {"VDD": "+3V3", "SPI1_SCK": "SCK", "USART3_TX": "TX", "I2C2_SCL": "SCL",
                                                "PH0": "X", "NOT_A_PIN": "Y"}})
    msg = bad.get("error", "")
    assert "Nothing was added" in msg and "Pin conflict" in msg and "PB10" in msg          # USART3_TX vs I2C2_SCL
    assert "used by the block itself" in msg and "not a port" in msg
    assert not s.plan().components                                                           # all-or-nothing
    r = run_tool(s, "add_block", {"block": "stm32f405_core", "instance": "mcu",
                                  "connect": {"VDD": "+3V3", "SPI1_SCK": "SCK", "USART3_TX": "TX"}})
    assert r["function_pins"]["SPI1_SCK"] == "PA5" and not r["problems"], r
    plan = s.plan()
    u = next(c.ref for c in plan.components if c.lib_id.endswith("STM32F405RGTx"))
    assert f"{u}.21" in plan.net("SCK").nodes                     # PA5 = pin 21
    assert f"{u}.2" in plan.no_connect                            # PC13 unused → NC
    # peripherals added later with block_connect; a pin already in use is refused
    r = run_tool(s, "block_connect", {"instance": "mcu", "connect": {"I2C1_SCL": "SCL1", "I2C2_SCL": "SCL2"}})
    assert r["connected"] == {"I2C1_SCL": "SCL1"} and any("PB10" in p for p in r["problems"]), r
    assert f"{u}.61" in s.plan().net("SCL1").nodes               # PB8 = pin 61, was NC, now connected


@pytest.mark.skipif(not os.path.exists(LIB), reason="library index not built")
def test_missing_required_port_is_reported(tmp_path, rlhome):
    s = _project(tmp_path)
    r = run_tool(s, "add_block", {"block": "icm20602_spi", "instance": "imu", "connect": {"VDD": "+3V3"}})
    assert "Required port SCK" in r.get("error", "") and not s.plan().components


@pytest.mark.skipif(not os.path.exists(LIB), reason="library index not built")
def test_small_board_from_blocks_verifies(tmp_path, rlhome, has_cli):
    s = _project(tmp_path)
    for blk, inst, params, conn in [
        ("usb_c_device", "usb", {"vbus_diode": False}, {"VBUS": "VBUS", "DP": "USB_DP", "DM": "USB_DM"}),
        ("ldo_3v3", "ldo", {}, {"VIN": "VBUS", "VOUT": "+3V3"}),
        ("stm32f405_core", "mcu", {"boot_button": False}, {"VDD": "+3V3", "USB_DP": "USB_DP", "USB_DM": "USB_DM", "PB5": "LED"}),
        ("led_indicator", "led", {}, {"IN": "LED"})]:
        r = run_tool(s, "add_block", {"block": blk, "instance": inst, "params": params, "connect": conn})
        assert not r.get("problems") and not r.get("error"), r
    rv = run_tool(s, "plan_review", {})
    assert rv["ready_to_draw"] and not rv["errors"], rv
    run_tool(s, "place_parts", {"mode": "file", "labels": True})
    v = run_tool(s, "verify_schematic", {})
    assert v["progress_percent"] == 100.0 and not v["errors"], v
