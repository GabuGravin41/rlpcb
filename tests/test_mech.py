import os

from rlpcb.pcb.mech import check_envelope, export_mechanical

FC = os.path.join(os.path.dirname(__file__), "..", "examples", "drone_fc", "output", "rl_fc_f405", "rl_fc_f405.kicad_pcb")


def _mech(tmp_path):
    return export_mechanical(FC, str(tmp_path / "fc.mech.json"))


def test_mech_describes_the_fc(tmp_path):
    m = _mech(tmp_path)
    assert m["schema"] == "rl-mech/1" and m["outline_mm"]["size"] == [36.0, 36.0]
    assert sorted((round(abs(h["at_mm"][0]), 2), round(abs(h["at_mm"][1]), 2)) for h in m["mounting_holes"]) == [(15.25, 15.25)] * 4
    usb = next(c for c in m["connectors"] if c["mate"] == "usb-c")
    assert usb["ref"] == "J2" and usb["edge"] == "+y" and usb["plug_mm"]
    assert next(c for c in m["connectors"] if c["ref"] == "J6")["populated"] is False
    assert m["height_mm"]["bottom"] > 0 and m["height_mm"]["top"] >= 3.0


def test_envelope_checks(tmp_path):
    m = _mech(tmp_path)
    ok = {"max_outline_mm": [40, 40], "mount_pattern_mm": 30.5, "keepout_height_mm": {"top": 10, "bottom": 3.7},
          "required_ports": [{"mate": "usb-c", "edges": ["+y"]}]}
    assert check_envelope(m, ok)["summary"]["error"] == 0
    bad = {"max_outline_mm": [30, 30], "mount_pattern_mm": 20, "keepout_height_mm": {"top": 2, "bottom": 1},
           "required_ports": [{"mate": "usb-c", "edges": ["-x"]}]}
    rules = {f["rule"] for f in check_envelope(m, bad)["findings"] if f["severity"] == "error"}
    assert rules == {"mech_outline", "mech_mounting", "mech_height", "mech_port"}


def test_mech_check_covers_every_product(tmp_path):
    """A board used in two products is checked against both envelopes; a problem names its product."""
    import json
    import shutil
    from rlpcb.agent.tools import Session, run_tool
    proj = tmp_path / "fc"
    shutil.copytree(os.path.dirname(FC), proj, ignore=shutil.ignore_patterns("fab", "*.routed.kicad_pcb"))
    ok = {"schema": "rl-envelope/1", "product": "drone", "max_outline_mm": [40, 40], "mount_pattern_mm": 30.5,
          "keepout_height_mm": {"top": 10, "bottom": 3.7}}
    small = dict(ok, product="tiny box", max_outline_mm=[30, 30])
    (proj / "enclosure.json").write_text(json.dumps(ok))
    (proj / "enclosure.tiny_box.json").write_text(json.dumps(small))
    s = Session()
    run_tool(s, "open_project", {"path": str(proj)}, actor="engineer")
    r = run_tool(s, "mech_check", {}, actor="engineer")
    assert {x["product"] for x in r["products"]} == {"drone", "tiny box"}
    errs = [f for f in r["findings"] if f["severity"] == "error"]
    assert errs and {f["product"] for f in errs} == {"tiny box"}
