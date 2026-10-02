"""File-mode flip must match KiCad's own FOOTPRINT::Flip (needs pcbnew; skipped otherwise)."""
import glob
import os
import random
import tempfile

import pytest

pcbnew = pytest.importorskip("pcbnew")

from rlpcb.kicad.sexpr import dump, parse
from rlpcb.pcb.assist import flip_footprint_node

FPROOT = "/usr/share/kicad/footprints"
PICKS = ["Capacitor_SMD.pretty/C_0402_1005Metric", "Package_QFP.pretty/LQFP-64_10x10mm_P0.5mm",
         "Connector_USB.pretty/USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
         "Package_SO.pretty/TI_SO-PowerPAD-8_ThermalVias", "Connector_JST.pretty/JST_SH_SM08B-SRSS-TB_1x08-1MP_P1.00mm_Horizontal",
         "Crystal.pretty/Crystal_SMD_3225-4Pin_3.2x2.5mm", "Package_LGA.pretty/Bosch_LGA-8_2x2.5mm_P0.65mm_ClockwisePinNumbering",
         "Button_Switch_SMD.pretty/SW_SPST_TL3342", "MountingHole.pretty/MountingHole_3.2mm_M3_Pad_Via",
         "Package_TO_SOT_SMD.pretty/SOT-23-6", "Diode_SMD.pretty/D_SMA", "Inductor_SMD.pretty/L_Bourns_SRP7028A_7.3x6.6mm"]


def _snapshot(board):
    out = {}
    for f in board.GetFootprints():
        pads = sorted((p.GetNumber(), round(pcbnew.ToMM(p.GetPosition().x), 3), round(pcbnew.ToMM(p.GetPosition().y), 3),
                       round(p.GetOrientationDegrees() % 180, 2), tuple(sorted(p.GetLayerSet().Seq())))
                      for p in f.Pads())
        gfx = sorted((g.GetLayer(), round(pcbnew.ToMM(g.GetStart().x), 3), round(pcbnew.ToMM(g.GetStart().y), 3),
                      round(pcbnew.ToMM(g.GetEnd().x), 3), round(pcbnew.ToMM(g.GetEnd().y), 3))
                     for g in f.GraphicalItems() if isinstance(g, pcbnew.PCB_SHAPE) and g.GetShape() != pcbnew.SHAPE_T_ARC)
        texts = sorted((t.GetLayer(), round(pcbnew.ToMM(t.GetPosition().x), 3), round(pcbnew.ToMM(t.GetPosition().y), 3),
                        t.IsMirrored(), round(t.GetTextAngleDegrees() % 360, 1)) for t in (f.Reference(), f.Value()))
        arcs = sorted((g.GetLayer(), round(pcbnew.ToMM(g.GetArcMid().x), 3), round(pcbnew.ToMM(g.GetArcMid().y), 3))
                      for g in f.GraphicalItems() if isinstance(g, pcbnew.PCB_SHAPE) and g.GetShape() == pcbnew.SHAPE_T_ARC)
        gfx = gfx + arcs
        out[f.GetReference()] = (f.GetLayer(), round(f.GetOrientationDegrees() % 360, 2), pads, gfx, texts)
    return out


def _norm_seg(t):
    lay, x0, y0, x1, y1 = t
    return (lay,) + tuple(sorted([(x0, y0), (x1, y1)]))


def test_flip_matches_pcbnew():
    tmp = tempfile.mkdtemp()
    board = pcbnew.BOARD()
    rnd = random.Random(4)
    n = 0
    for pick in PICKS:
        lib, name = pick.split("/")
        for rot in (0, 90, 30, -135):
            m = pcbnew.FootprintLoad(os.path.join(FPROOT, lib), name)
            if m is None:
                continue
            n += 1
            m.SetReference(f"X{n}")
            m.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(20 + 25 * (n % 8)), pcbnew.FromMM(20 + 25 * (n // 8))))
            m.SetOrientationDegrees(rot)
            board.Add(m)
    base = os.path.join(tmp, "base.kicad_pcb")
    board.Save(base)
    # reference: pcbnew flip
    ref_b = pcbnew.LoadBoard(base)
    for f in ref_b.GetFootprints():
        f.Flip(f.GetPosition(), False)
    # ours: text-level flip
    text = open(base, encoding="utf-8").read()
    root = parse(text)
    edits = []
    for fp in root.children("footprint"):
        flip_footprint_node(fp)
        edits.append((fp.start, fp.end, dump(fp, 1)))
    for s, e, rep in sorted(edits, key=lambda t: -t[0]):
        text = text[:s] + rep + text[e:]
    ours = os.path.join(tmp, "ours.kicad_pcb")
    open(ours, "w", encoding="utf-8").write(text)
    a, b = _snapshot(ref_b), _snapshot(pcbnew.LoadBoard(ours))
    assert a.keys() == b.keys() and len(a) >= 40
    for ref in a:
        la, ra, pa, ga, ta = a[ref]
        lb, rb, pb, gb, tb = b[ref]
        assert la == lb, ref
        assert ra == rb, (ref, ra, rb)
        assert pa == pb, (ref, [x for x in pa if x not in pb][:3], [x for x in pb if x not in pa][:3])
        norm = lambda g: sorted(repr(_norm_seg(x) if len(x) == 5 else x) for x in g)
        assert norm(ga) == norm(gb), ref
        assert ta == tb, (ref, ta, tb)


def test_move_to_bottom_with_rotation_matches_pcbnew():
    from rlpcb.pcb.assist import move_footprints_in_file
    tmp = tempfile.mkdtemp()
    board = pcbnew.BOARD()
    for i, pick in enumerate(PICKS[:6]):
        lib, name = pick.split("/")
        m = pcbnew.FootprintLoad(os.path.join(FPROOT, lib), name)
        m.SetReference(f"X{i}")
        m.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(30 * i), pcbnew.FromMM(10)))
        m.SetOrientationDegrees(30 * i)
        board.Add(m)
    base = os.path.join(tmp, "b.kicad_pcb")
    board.Save(base)
    ref = pcbnew.LoadBoard(base)
    moves = []
    for i, f in enumerate(ref.GetFootprints()):
        f.Flip(f.GetPosition(), False)
        f.SetOrientationDegrees(90)
        f.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(5 + 30 * i), pcbnew.FromMM(50)))
        moves.append({"ref": f.GetReference(), "x_mm": 5 + 30 * i, "y_mm": 50, "rotation": 90, "side": "bottom"})
    r = move_footprints_in_file(base, moves)
    assert len(r["flipped"]) == 6
    a, b = _snapshot(ref), _snapshot(pcbnew.LoadBoard(base))
    for k in a:
        assert a[k][:3] == b[k][:3], k
