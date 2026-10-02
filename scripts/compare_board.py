"""Compare schematic connectivity with the pad nets stored in the project's .kicad_pcb (oracle for KiCad 9/10 demos)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import defaultdict
from rlpcb.kicad.schematic import Hierarchy
from rlpcb.kicad.connectivity import Connectivity
from rlpcb.pcb.board import Board

def run(pro, verbose=False):
    pcb = pro[:-len(".kicad_pro")] + ".kicad_pcb"
    if not os.path.exists(pcb): return
    b = Board(pcb)
    board_refs = {f.ref for f in b.footprints}
    groups = defaultdict(set)
    for f in b.footprints:
        for p in f.pads:
            if p.net and not p.net.startswith("unconnected-") and p.number:
                groups[p.net].add(f"{f.ref}.{p.number}")
    bparts = {frozenset(v) for v in groups.values() if len(v) > 1}
    c = Connectivity(Hierarchy(pro))
    mine = set()
    for n, pins in c.netlist().items():
        s = frozenset(p for p in pins if p.split(".")[0] in board_refs)
        if len(s) > 1: mine.add(s)
    missing, extra = bparts - mine, mine - bparts
    print(f"{'OK ' if not missing and not extra else 'BAD'} {os.path.basename(pro)} board={len(bparts)} mine={len(mine)} missing={len(missing)} extra={len(extra)}")
    if verbose:
        for m in list(missing)[:4]: print("  board-only", sorted(m)[:8])
        for m in list(extra)[:4]: print("  mine-only ", sorted(m)[:8])

for p in sys.argv[1:]:
    try: run(p, True)
    except Exception as e: print("ERR", p, e)
