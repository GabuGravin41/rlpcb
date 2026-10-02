import os

import pytest

from rlpcb.agent.tools import Session, run_tool

LIB = os.path.join(os.environ.get("RLPCB_HOME") or os.path.join(os.path.expanduser("~"), ".rlpcb"), "library_index.db")


def _board(root, name, blocks, extra=None):
    s = Session()
    run_tool(s, "create_project", {"folder": str(root), "name": name})
    for blk, inst, params, conn in blocks:
        r = run_tool(s, "add_block", {"block": blk, "instance": inst, "params": params, "connect": conn})
        assert not r.get("error"), r
    for net, kw in (extra or {}).items():
        run_tool(s, "plan_connect", {"net": net, **kw})
    return s


def _system(tmp_path, sensor_conn, sensor_5v_current=0.2):
    main = _board(tmp_path, "main", [
        ("ldo_3v3", "ldo", {}, {"VIN": "+5V", "VOUT": "+3V3"}),
        ("stm32f405_core", "mcu", {"boot_button": False},
         {"VDD": "+3V3", "USART1_TX": "UART_TX", "USART1_RX": "UART_RX", "I2C1_SCL": "I2C_SCL", "I2C1_SDA": "I2C_SDA"}),
        ("bmp280_i2c", "baro", {}, {"VDD": "+3V3", "SCL": "I2C_SCL", "SDA": "I2C_SDA"}),
        ("connector", "link", {"pins": 6, "label": "LINK"},
         {"1": "+5V", "2": "GND", "3": "UART_TX", "4": "UART_RX", "5": "I2C_SCL", "6": "I2C_SDA"})])
    sensor = _board(tmp_path, "sensor", [
        ("ldo_3v3", "ldo", {}, {"VIN": "+5V_IN", "VOUT": "+3V3"}),
        ("stm32f405_core", "mcu", {"boot_button": False},
         {"VDD": "+3V3", "USART2_TX": "UART_TX", "USART2_RX": "UART_RX", "I2C1_SCL": "I2C_SCL", "I2C1_SDA": "I2C_SDA"}),
        ("connector", "link", {"pins": 6, "label": "LINK"}, sensor_conn)],
        {"+5V_IN": {"pins": ["U1.VIN"], "voltage_v": 5, "current_a": sensor_5v_current}})
    s = Session()
    folder = str(tmp_path / "sys")
    run_tool(s, "system_create", {"folder": folder, "name": "demo"})
    run_tool(s, "system_add_board", {"folder": folder, "name": "main", "project": str(tmp_path / "main")})
    run_tool(s, "system_add_board", {"folder": folder, "name": "sensor", "project": str(tmp_path / "sensor")})
    run_tool(s, "system_add_harness", {"folder": folder, "a_board": "main", "a_ref": "J1", "b_board": "sensor", "b_ref": "J1",
                                       "pin_current_a": 1.0})
    run_tool(s, "system_add_supply", {"folder": folder, "board": "main", "net": "+5V", "capacity_a": 0.5})
    return s, folder


@pytest.mark.skipif(not os.path.exists(LIB), reason="library index not built")
def test_correct_harness_is_clean(tmp_path, rlhome):
    s, folder = _system(tmp_path, {"1": "+5V_IN", "2": "GND", "3": "UART_RX", "4": "UART_TX", "5": "I2C_SCL", "6": "I2C_SDA"})
    r = run_tool(s, "system_check", {"folder": folder})
    assert r["summary"].get("error", 0) == 0, r["findings"]
    assert len(r["pins"]) == 6


@pytest.mark.skipif(not os.path.exists(LIB), reason="library index not built")
def test_broken_harness_is_caught(tmp_path, rlhome):
    # TX meets TX, +3V3 meets +5V, GND meets a signal, and the sensor draws more than the supply gives
    s, folder = _system(tmp_path, {"1": "+3V3", "2": "I2C_SDA", "3": "UART_TX", "4": "UART_RX", "5": "I2C_SCL", "6": "GND"},
                        sensor_5v_current=0.8)
    r = run_tool(s, "system_check", {"folder": folder})
    rules = {f["rule"] for f in r["findings"] if f["severity"] == "error"}
    assert {"uart_direction", "voltage_mismatch", "ground_mismatch"} <= rules, r["findings"]


@pytest.mark.skipif(not os.path.exists(LIB), reason="library index not built")
def test_supply_capacity(tmp_path, rlhome):
    s, folder = _system(tmp_path, {"1": "+5V_IN", "2": "GND", "3": "UART_RX", "4": "UART_TX", "5": "I2C_SCL", "6": "I2C_SDA"},
                        sensor_5v_current=0.8)
    r = run_tool(s, "system_check", {"folder": folder})
    assert any(f["rule"] == "supply_capacity" and f["severity"] == "error" for f in r["findings"]), r["findings"]
