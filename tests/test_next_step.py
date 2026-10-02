import os

import pytest

from rlpcb.agent.tools import Session, run_tool

LIB = os.path.join(os.environ.get("RLPCB_HOME") or os.path.join(os.path.expanduser("~"), ".rlpcb"), "library_index.db")


@pytest.mark.skipif(not os.path.exists(LIB), reason="library index not built")
def test_next_step_walks_the_flow(tmp_path, rlhome):
    s = Session()
    run_tool(s, "create_project", {"folder": str(tmp_path), "name": "n"})
    assert run_tool(s, "next_step", {})["next_action"]["tool"] == "plan_set_info"
    run_tool(s, "plan_set_info", {"requirements": {"input": "USB 5 V", "size": "30x20 mm"}})
    assert run_tool(s, "next_step", {})["next_action"]["tool"] == "list_blocks"
    run_tool(s, "add_block", {"block": "ldo_3v3", "instance": "ldo", "connect": {"VIN": "+5V", "VOUT": "+3V3"}})
    run_tool(s, "add_block", {"block": "led_indicator", "instance": "led", "connect": {"IN": "+3V3"}})
    n = run_tool(s, "next_step", {})
    assert n["next_action"]["tool"] == "place_parts", n
    run_tool(s, "place_parts", {"mode": "file", "labels": True})
    n = run_tool(s, "next_step", {})
    assert n["stage"] == "PCB created from schematic (F8)", n
    assert "F8" in n["next_action"]["ask_user_to"]
