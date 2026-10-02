import os
import pytest
from rlpcb.agent.tools import Session, run_tool

LIB = os.path.join(os.environ.get("RLPCB_HOME") or os.path.join(os.path.expanduser("~"), ".rlpcb"), "library_index.db")

@pytest.mark.skipif(not os.path.exists(LIB), reason="library index not built")
def test_plan_place_label_verify(tmp_path, rlhome, has_cli):
    s = Session()
    r = run_tool(s, "create_project", {"folder": str(tmp_path), "name": "t"})
    assert "project" in r, r
    r = run_tool(s, "plan_add_components", {"components": [
        {"ref": "U1", "lib_id": "Regulator_Linear:AMS1117-3.3"},
        {"ref": "C1", "lib_id": "Device:C", "value": "10u", "footprint": "Capacitor_SMD:C_0805_2012Metric"},
        {"ref": "C2", "lib_id": "Device:C", "value": "22u", "footprint": "Capacitor_SMD:C_0805_2012Metric"}]})
    assert not r["problems"], r
    assert run_tool(s, "plan_connect", {"net": "VIN", "pins": ["U1.VI", "C1.1"]}).get("nodes")
    assert run_tool(s, "plan_connect", {"net": "+3V3", "pins": ["U1.VO", "C2.1"]}).get("nodes")
    assert run_tool(s, "plan_connect", {"net": "GND", "pins": ["U1.GND", "C1.2", "C2.2"]}).get("nodes")
    rv = run_tool(s, "plan_review", {})
    assert rv["ready_to_draw"], rv
    r = run_tool(s, "place_parts", {"mode": "file", "labels": True})
    assert len(r["placed"]) == 3, r
    v = run_tool(s, "verify_schematic", {})
    assert v["progress_percent"] == 100.0, v
    assert not v["errors"]
    # KiCad itself must agree: its netlist of the written file equals the plan
    from tests.test_connectivity import _kicad_nets
    got = _kicad_nets(s.sch_path)
    want = {frozenset(n.nodes) for n in s.plan().nets}
    assert want <= got, (want, got)
