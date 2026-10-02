import os

from rlpcb.pcb.ampacity import rise_for, width_for

EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "drone_fc", "output",
                       "rl_fc_f405")


def test_ipc2221_numbers():
    assert 1.3 < width_for(3.0) < 1.45          # 3 A, 10 °C, 1 oz outer
    assert rise_for(2.5, 0.15) > 100            # a 0.15 mm switch node at 2.5 A is far too hot
    assert rise_for(2.0, 0.4, inner=True) > rise_for(2.0, 0.4)


def test_nets_with_current_get_sized_classes():
    from rlpcb.agent.tools import Session
    from rlpcb.pcb.assist import netclasses_from_plan
    s = Session()
    from rlpcb.agent.tools import run_tool
    run_tool(s, "open_project", {"path": EXAMPLE}, actor="engineer")
    cls = netclasses_from_plan(s.plan())
    assert "BUCK_SW" in cls["HighCurrent"]      # a switch node with a current but no class is sized by its current
    assert "+5V" in cls["Power2A"]


def test_review_has_no_power_concerns_on_reworked_board():
    from rlpcb.agent.tools import Session, run_tool
    s = Session()
    run_tool(s, "open_project", {"path": EXAMPLE}, actor="engineer")
    r = run_tool(s, "review_layout", {"focus": "power"}, actor="engineer")
    assert not [p for p in r["points"] if p["level"] == "concern"], r["points"]
    assert any("copper pour" in p["message"] for p in r["points"])
