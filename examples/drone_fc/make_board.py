"""Demo helper: the equivalent of pressing F8 ("Update PCB from Schematic") in KiCad, for the cloud demo where there
is no KiCad GUI. Builds <project>.kicad_pcb from the schematic's netlist with pcbnew's Python API (KiCad 7+):
36x36 mm 4-layer outline, four M3 holes on 30.5 mm centres, every footprint loaded with its nets, parked below
the board exactly like F8 does. On your own computer you press F8 instead of running this.

    python examples/drone_fc/make_board.py <project-dir>
"""
import os
import subprocess
import sys
import tempfile

import pcbnew

from rlpcb.kicad.sexpr import parse_file

proj = os.path.abspath(sys.argv[1])
name = os.path.basename(proj)
sch = os.path.join(proj, name + ".kicad_sch")
out = os.path.join(proj, name + ".kicad_pcb")
FPROOT = os.environ.get("KICAD7_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
MM = pcbnew.FromMM

net_file = os.path.join(tempfile.mkdtemp(), "n.net")
subprocess.run(["kicad-cli", "sch", "export", "netlist", "-o", net_file, sch], check=True, capture_output=True)
root = parse_file(net_file)

board = pcbnew.BOARD()
board.SetCopperLayerCount(4)
ds = board.GetDesignSettings()
ds.SetBoardThickness(MM(1.6))

# outline: 36 x 36 mm, 3 mm corner radius, origin at (100, 100)
X0, Y0, W, R = 100.0, 100.0, 36.0, 3.0


def seg(a, b):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(pcbnew.VECTOR2I(MM(a[0]), MM(a[1])))
    s.SetEnd(pcbnew.VECTOR2I(MM(b[0]), MM(b[1])))
    s.SetLayer(pcbnew.Edge_Cuts)
    s.SetWidth(MM(0.1))
    board.Add(s)


def arc(c, start, angle):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_ARC)
    s.SetCenter(pcbnew.VECTOR2I(MM(c[0]), MM(c[1])))
    s.SetStart(pcbnew.VECTOR2I(MM(start[0]), MM(start[1])))
    s.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(angle, pcbnew.DEGREES_T))
    s.SetLayer(pcbnew.Edge_Cuts)
    s.SetWidth(MM(0.1))
    board.Add(s)


x1, y1 = X0 + W, Y0 + W
seg((X0 + R, Y0), (x1 - R, Y0)); seg((x1, Y0 + R), (x1, y1 - R))
seg((x1 - R, y1), (X0 + R, y1)); seg((X0, y1 - R), (X0, Y0 + R))
arc((x1 - R, Y0 + R), (x1 - R, Y0), 90); arc((x1 - R, y1 - R), (x1, y1 - R), 90)
arc((X0 + R, y1 - R), (X0 + R, y1), 90); arc((X0 + R, Y0 + R), (X0, Y0 + R), 90)

nets = {}


def net(n):
    if n not in nets:
        ni = pcbnew.NETINFO_ITEM(board, n)
        board.Add(ni)
        nets[n] = ni
    return nets[n]


pad_net = {}
for n in root.child("nets").children("net"):
    nm = n.value("name")
    for node in n.children("node"):
        pad_net[(node.value("ref"), node.value("pin"))] = nm

px, py = X0, Y0 + W + 8  # parking area below the board, like F8
count = 0
for comp in root.child("components").children("comp"):
    ref, val, fp = comp.value("ref"), comp.value("value"), comp.value("footprint")
    if not fp:
        continue
    lib, fpname = fp.split(":", 1)
    m = pcbnew.FootprintLoad(os.path.join(FPROOT, lib + ".pretty"), fpname)
    if m is None:
        print("missing footprint", fp)
        continue
    m.SetReference(ref)
    m.SetValue(val)
    m.SetFPID(pcbnew.LIB_ID(lib, fpname))
    for pad in m.Pads():
        nm = pad_net.get((ref, pad.GetNumber()))
        if nm:
            pad.SetNet(net(nm))
    board.Add(m)
    bb = m.GetBoundingBox(False, False)
    w = pcbnew.ToMM(bb.GetWidth())
    if px + w > X0 + 120:
        px, py = X0, py + 14
    m.SetPosition(pcbnew.VECTOR2I(MM(px + w / 2), MM(py)))
    px += w + 2
    count += 1

for i, (hx, hy) in enumerate([(X0 + 2.75, Y0 + 2.75), (x1 - 2.75, Y0 + 2.75), (x1 - 2.75, y1 - 2.75), (X0 + 2.75, y1 - 2.75)]):
    h = pcbnew.FootprintLoad(os.path.join(FPROOT, "MountingHole.pretty"), "MountingHole_3.2mm_M3")
    h.SetReference(f"H{i + 1}")
    h.SetPosition(pcbnew.VECTOR2I(MM(hx), MM(hy)))
    board.Add(h)

# ground planes on In1 (solid GND) and bottom pour; filled later by DRC --refill / KiCad
for layer, netname in ((pcbnew.In1_Cu, "GND"), (pcbnew.B_Cu, "GND"), (pcbnew.In2_Cu, "+3V3")):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(net(netname))
    ol = z.Outline()
    ol.NewOutline()
    for (x, y) in ((X0 + 0.5, Y0 + 0.5), (x1 - 0.5, Y0 + 0.5), (x1 - 0.5, y1 - 0.5), (X0 + 0.5, y1 - 0.5)):
        ol.Append(MM(x), MM(y))
    z.SetMinThickness(MM(0.2))
    z.SetLocalClearance(MM(0.25))
    board.Add(z)

board.Save(out)
print(f"board written: {out}  ({count} footprints + 4 mounting holes, 4 layers, 36x36 mm)")
