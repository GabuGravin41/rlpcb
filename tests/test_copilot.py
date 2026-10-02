"""Copilot: modes, proposals, accept/reject, undo, journal, assurance; layout review; kickoff; explain; interface log."""
import json
import os
import shutil

import pytest

from rlpcb.agent.tools import Session, run_tool

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FC = os.path.join(HERE, "examples", "drone_fc", "output", "rl_fc_f405")


@pytest.fixture()
def proj(tmp_path, rlhome):
    d = tmp_path / "rl_fc_f405"
    shutil.copytree(FC, d, ignore=shutil.ignore_patterns("fab", "*.routed.*"))
    s = Session()
    assert "error" not in run_tool(s, "open_project", {"path": str(d)})
    run_tool(s, "copilot_mode", {"mode": "propose"}, actor="engineer")
    return s, d


PART = {"components": [{"ref": "R99", "lib_id": "Device:R", "value": "10k", "role": "test", "block": "mcu",
                        "footprint": "Resistor_SMD:R_0402_1005Metric"}]}


def test_propose_accept_undo(proj):
    s, d = proj
    r = run_tool(s, "plan_add_components", PART)
    assert r["proposal"] and "R99" in r["summary"]
    assert r["checks"]["errors_after"] == r["checks"]["errors_before"]
    assert "not_verified" in r["assurance"]
    assert not s.plan().comp("R99"), "a proposal must not touch the design"
    acc = run_tool(s, "proposal_accept", {"id": r["proposal"]}, actor="engineer")
    assert s.plan().comp("R99")
    run_tool(s, "undo", {"id": acc["journal_id"]})
    assert not s.plan().comp("R99")


def test_reject_keeps_reason_and_advise_blocks(proj):
    s, d = proj
    r = run_tool(s, "plan_add_components", PART)
    run_tool(s, "proposal_reject", {"id": r["proposal"], "reason": "use 4.7k"}, actor="engineer")
    fb = run_tool(s, "copilot_status", {})["recent_feedback"]
    assert fb[-1]["reason"] == "use 4.7k" and fb[-1]["status"] == "rejected"
    run_tool(s, "copilot_mode", {"mode": "advise", "scope": "board"}, actor="engineer")
    b = run_tool(s, "move_footprints", {"moves": [{"ref": "C11", "x_mm": 120, "y_mm": 120}]})
    assert b["blocked_by_mode"] == "advise"
    # the plan is still in propose mode (scopes are independent)
    assert run_tool(s, "plan_add_components", PART).get("proposal")


def test_do_mode_journal_and_drift_protection(proj):
    s, d = proj
    run_tool(s, "copilot_mode", {"mode": "do"}, actor="engineer")
    r = run_tool(s, "plan_add_components", PART)
    assert r["copilot"]["journal_id"] and s.plan().comp("R99")
    # a later edit to the same file blocks undo of the earlier one unless forced
    run_tool(s, "plan_set_info", {"decision": "later change"})
    with pytest.raises(Exception):
        from rlpcb.agent.copilot_pcb import copilot_for
        copilot_for(s).undo(r["copilot"]["journal_id"])
    j = run_tool(s, "design_journal", {})["entries"]
    assert [e["action"] for e in j][-2:] == ["plan_add_components", "plan_set_info"]


def test_board_proposal_and_layout_review(proj):
    s, d = proj
    r = run_tool(s, "move_footprints", {"moves": [{"ref": "C11", "x_mm": 120, "y_mm": 120}]})
    assert "C11" in r["summary"] and "moved" in r["summary"]
    cmp_ = run_tool(s, "compare_layouts", {"b": r["proposal"]})
    assert any(row["metric"].startswith("ratsnest") for row in cmp_["rows"])
    rv = run_tool(s, "review_layout", {})
    msgs = " ".join(p["message"] for p in rv["points"])
    assert "BUCK_SW" in msgs and "USB_DP/USB_DM" in msgs
    assert all(p["basis"] in ("measured", "rule of thumb") for p in rv["points"])


def test_decision_needs_engineer(proj):
    s, d = proj
    run_tool(s, "copilot_mode", {"mode": "do"}, actor="engineer")
    r = run_tool(s, "design_checks", {"acknowledge": [{"id": "x:y", "reason": "fine"}]})
    assert r.get("proposal"), "an AI acknowledging a warning must go to the engineer as a proposal"


def test_kickoff_and_apply(tmp_path, rlhome):
    s = Session()
    b = run_tool(s, "kickoff", {"idea": "battery powered wifi soil moisture sensor"})
    assert b["archetype"] == "iot_sensor_node" and b["questions"] and b["architecture"]
    assert run_tool(s, "kickoff", {"idea": "thermal receipt printer"})["archetype"] == "printer_system"
    os.environ["RLPCB_DEFAULT_MODE"] = "propose"
    try:
        r = run_tool(s, "kickoff_apply", {"folder": str(tmp_path), "name": "soil", "archetype": "iot_sensor_node"})
    finally:
        os.environ["RLPCB_DEFAULT_MODE"] = "do"
    assert r["proposal"] and not os.path.exists(tmp_path / "soil" / "soil.kicad_pro")
    run_tool(s, "proposal_accept", {"id": r["proposal"]}, actor="engineer")
    assert os.path.exists(tmp_path / "soil" / "soil.kicad_pro")
    assert os.path.exists(tmp_path / "soil" / "docs" / "requirements.md")


def test_explain(proj):
    s, d = proj
    roles = {r: run_tool(s, "explain_component", {"ref": r})["inferred_role"] for r in ("R8", "L1", "D1", "R11", "U7")}
    assert roles == {"R8": "pull-up resistor", "L1": "buck/boost inductor", "D1": "catch (freewheel) diode",
                     "R11": "USB-C CC pull-down (5.1 kΩ)", "U7": "ESD / surge protection"}
    assert run_tool(s, "explain_net", {"net": "BUCK_SW"})["kind"] == "switching"


def test_interface_log(tmp_path):
    from rlpcb.pcb import interface as I
    old = json.load(open(os.path.join(FC, "rl_fc_f405.mech.json")))
    new = json.loads(json.dumps(old))
    j2 = next(c for c in new["connectors"] if c["ref"] == "J2")
    j2["at_mm"] = [j2["at_mm"][0] + 4, j2["at_mm"][1]]
    j2["edge"] = "+x"
    new["height_mm"]["top"] += 2
    ch = I.mech_diff(old, new)
    assert {c["what"] for c in ch} == {"connector", "part height"}
    p = tmp_path / "b.mech.json"
    p.write_text(json.dumps(old))
    e = I.write_with_notice(str(p), new, "pcb", I.mech_diff)
    assert e and I.unseen(str(tmp_path), "cad")[0]["id"] == e["id"]
    I.mark_seen(str(tmp_path), "cad", [e["id"]], "ok")
    assert not I.unseen(str(tmp_path), "cad")
