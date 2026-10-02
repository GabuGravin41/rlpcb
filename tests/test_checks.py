import os

import pytest

from rlpcb.agent.tools import Session, run_tool
from rlpcb.design.checks import parse_current, parse_voltage

LIB = os.path.join(os.environ.get("RLPCB_HOME") or os.path.join(os.path.expanduser("~"), ".rlpcb"), "library_index.db")


def test_parsers():
    assert parse_voltage("10u 50V") == 50
    assert parse_voltage("+3V3") == 3.3
    assert parse_voltage("6V3") == 6.3
    assert parse_voltage("+5V") == 5
    assert parse_voltage("100n") is None
    assert parse_current("3.6A") == 3.6
    assert parse_current("500mA") == 0.5


def _rules(s):
    r = run_tool(s, "design_checks", {})
    return {(f["rule"], f["severity"]) for f in r["findings"]}, r


@pytest.mark.skipif(not os.path.exists(LIB), reason="library index not built")
def test_checks_catch_planted_problems(tmp_path, rlhome):
    s = Session()
    run_tool(s, "create_project", {"folder": str(tmp_path), "name": "c"})
    run_tool(s, "plan_set_info", {"requirements": {"size": "20x20 mm"}})
    # 1. an under-rated input cap on a 24 V rail
    run_tool(s, "add_block", {"block": "tps5430_buck", "instance": "buck", "params": {"vin_min": 12, "vin_max": 24},
                              "connect": {"VIN": "VIN24", "VOUT": "+5V"}})
    buck_cin = next(c for c in s.plan().components if c.block == "buck" and c.role.startswith("Input cap"))
    run_tool(s, "plan_add_components", {"components": [{"ref": "C99", "lib_id": "Device:C", "value": "10u 16V",
                                                        "footprint": "Capacitor_SMD:C_1206_3216Metric"}]})
    run_tool(s, "plan_connect", {"net": "VIN24", "pins": ["C99.1"], "voltage_v": 24})
    run_tool(s, "plan_connect", {"net": "GND", "pins": ["C99.2"]})
    # 2. I2C without pull-ups
    run_tool(s, "add_block", {"block": "bmp280_i2c", "instance": "baro", "params": {"pullups": False},
                              "connect": {"VDD": "+5V", "SCL": "I2C_SCL", "SDA": "I2C_SDA"}})
    # 3. a second source on +5V
    run_tool(s, "add_block", {"block": "usb_c_device", "instance": "usb", "connect": {"VOUT": "+5V", "DP": "DP", "DM": "DM"}})
    rules, r = _rules(s)
    assert ("cap_voltage", "error") in rules, r
    assert ("pullup", "warning") in rules, r
    assert ("multiple_sources", "warning") in rules, r
    assert any(f["rule"] == "board_fit" for f in r["findings"]), r      # a buck + USB-C on 20×20 mm is tight
    # the block's own caps are correctly rated: no finding names them
    assert not any(buck_cin.ref in f["refs"] for f in r["findings"] if f["rule"] == "cap_voltage")
    # plan_review surfaces the same findings
    rv = run_tool(s, "plan_review", {})
    assert any("[cap_voltage]" in e for e in rv["errors"]) and not rv["ready_to_draw"]


EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "drone_fc", "output", "rl_fc_f405")


@pytest.mark.skipif(not os.path.isdir(EXAMPLE), reason="example project missing")
def test_board_checks_flag_a_moved_decoupling_cap(tmp_path, rlhome):
    import shutil
    proj = tmp_path / "fc"
    shutil.copytree(EXAMPLE, proj)
    s = Session()
    run_tool(s, "open_project", {"path": str(proj)})
    base = run_tool(s, "design_checks", {})
    assert not [f for f in base["findings"] if f["rule"] == "decoupling_distance"], base
    plan = s.plan()
    cap = next(c.ref for c in plan.components if c.role.startswith("VDD pin"))
    run_tool(s, "move_footprints", {"moves": [{"ref": cap, "x_mm": 103.0, "y_mm": 125.0}], "method": "file"})
    r = run_tool(s, "design_checks", {})
    assert any(f["rule"] == "decoupling_distance" and cap in f["refs"] for f in r["findings"]), r


@pytest.mark.skipif(not os.path.exists(LIB), reason="library index not built")
def test_checks_catch_weak_model_mistakes(tmp_path, rlhome):
    """Mistakes a small model actually made in the evaluation (docs/EVALUATION.md)."""
    s = Session()
    run_tool(s, "create_project", {"folder": str(tmp_path), "name": "w"})
    run_tool(s, "plan_add_components", {"components": [
        {"ref": "U1", "lib_id": "MCU_ST_STM32F4:STM32F405RGTx"},
        {"ref": "U2", "lib_id": "Regulator_Linear:NCP1117-3.3_SOT223"},
        {"ref": "U3", "lib_id": "Sensor_Pressure:BMP280"},
        {"ref": "J1", "lib_id": "Connector:USB_C_Receptacle_USB2.0_16P"},
        {"ref": "D1", "lib_id": "Device:LED", "footprint": "LED_SMD:LED_0603_1608Metric"},
        {"ref": "R1", "lib_id": "Device:R", "value": "1M", "footprint": "Resistor_SMD:R_0402_1005Metric"}]})
    C = lambda net, pins: run_tool(s, "plan_connect", {"net": net, "pins": pins})
    C("GND", ["U1.VSS", "U2.VO", "D1.A", "R1.2", "J1.GND"])        # LDO output on GND, LED backwards
    C("+3V3", ["U2.GND", "U1.VDD"])                                # LDO ground pin on the rail
    C("USB_DP", ["U1.PA11", "J1.A6"])                              # D+ on the D- pin; B6 left open
    C("USB_DM", ["U1.PA12", "J1.A7", "J1.B7"])
    C("CC1", ["J1.CC1", "R1.1"])                                   # 1 MΩ instead of 5.1 kΩ
    C("VCAP", ["U1.VCAP_1", "U1.VCAP_2"])                          # VCAPs tied together, no cap
    C("LED", ["D1.K", "U1.PB5"])
    run_tool(s, "plan_no_connect", {"pins": ["U3.SDO"]})           # BMP280 address pin marked NC
    r = run_tool(s, "design_checks", {})
    rules = {f["rule"] for f in r["findings"] if f["severity"] == "error"}
    for want in ("pin_role", "led_polarity", "mcu_pin_function", "usb_c_cc", "usb_c_data", "stm32_vcap", "must_connect"):
        assert want in rules, (want, sorted(rules))
