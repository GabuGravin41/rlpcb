"""Compare RL PCB connectivity against kicad-cli netlist export."""
import sys, os, subprocess, glob, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rlpcb.kicad.sexpr import parse_file
from rlpcb.kicad.schematic import Hierarchy
from rlpcb.kicad.connectivity import Connectivity

def kicad_netlist(sch):
    out = tempfile.mktemp(suffix=".net")
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, sch], capture_output=True)
    root = parse_file(out)
    nets = {}
    for net in root.child("nets").children("net"):
        name = net.value("name")
        pins = {f"{n.value('ref')}.{n.value('pin')}" for n in net.children("node")}
        pins = {p for p in pins if not p.startswith("#")}
        if pins: nets[name] = frozenset(pins)
    return nets

def compare(sch, verbose=False):
    k = kicad_netlist(sch)
    c = Connectivity(Hierarchy(sch))
    mine = {n: frozenset(v) for n, v in c.netlist().items()}
    ks, ms = set(k.values()), set(mine.values())
    # nets with single pin: kicad includes them too
    missing = ks - ms; extra = ms - ks
    ok = not missing and not extra
    print(f"{'OK ' if ok else 'BAD'} {os.path.basename(sch)}: kicad={len(ks)} mine={len(ms)} missing={len(missing)} extra={len(extra)}")
    if verbose and not ok:
        for m in list(missing)[:8]: print("  kicad-only:", sorted(m)[:12], [n for n,v in k.items() if v==m])
        for m in list(extra)[:8]: print("  mine-only :", sorted(m)[:12], [n for n,v in mine.items() if v==m])
    return ok

if __name__ == "__main__":
    for s in sys.argv[1:]:
        try: compare(s, True)
        except Exception as e:
            import traceback; traceback.print_exc()
