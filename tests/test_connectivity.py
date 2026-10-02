import glob, os, subprocess, tempfile, pytest
from rlpcb.kicad.sexpr import parse_file
from rlpcb.kicad.schematic import Hierarchy
from rlpcb.kicad.connectivity import Connectivity, expand_bus
from rlpcb.kicad.paths import kicad_cli

def _kicad_nets(sch):
    out = tempfile.mktemp(suffix=".net")
    subprocess.run([kicad_cli(), "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, sch], capture_output=True)
    if not os.path.exists(out):
        pytest.skip("kicad-cli could not export " + sch)
    nets = set()
    for n in parse_file(out).child("nets").children("net"):
        pins = frozenset(f"{x.value('ref')}.{x.value('pin')}" for x in n.children("node") if not str(x.value('ref')).startswith("#"))
        if pins:
            nets.add(pins)
    return nets

def test_expand_bus():
    assert expand_bus("D[0..3]") == ["D0", "D1", "D2", "D3"]
    assert expand_bus("USB{DP DM}") == ["USB.DP", "USB.DM"]
    assert expand_bus("X{U}", {"U": ["A", "B"]}) == ["X.A", "X.B"]
    assert expand_bus("SPI_{HUB}") == []  # subscript markup, not a bus

def test_matches_kicad_netlist_on_demos(demos, has_cli):
    roots = [p[:-len(".kicad_pro")] + ".kicad_sch" for p in glob.glob(os.path.join(demos, "*", "*.kicad_pro"))]
    roots = [r for r in roots if os.path.exists(r)]
    assert roots
    for sch in roots:
        mine = {frozenset(v) for v in Connectivity(Hierarchy(sch)).netlist().values()}
        assert mine == _kicad_nets(sch), sch
