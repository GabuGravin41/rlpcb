"""Finish an autorouted board with KiCad's own geometry and DRC (runs in KiCad's Python: `import pcbnew`).

Freerouting typically leaves a handful of connections. This module closes them without touching anything that
already passes DRC:

  * plane stitching: an SMD pad on a plane net (GND, +3V3 …) that is not connected gets a short stub and a via to its
    plane, placed where it clears every other-net item on every copper layer;
  * a small grid router (A*, 0.05 mm grid, 4 layers, vias) for the remaining two-point connections, with outer layers
    preferred and inner (plane) layers penalised;
  * cleanup: dangling stubs removed, stitches that DRC rejects are taken out again.

Every round ends with a zone refill and a full KiCad DRC; the report decides what is still open.

    python -m rlpcb.pcb.finish in.kicad_pcb out.kicad_pcb [--planes GND:In1.Cu,B.Cu +3V3:In2.Cu]
"""
from __future__ import annotations

import heapq
import math
import re
import sys
from collections import Counter
from typing import Dict, List, Optional, Tuple

import numpy as np
import pcbnew

MM = pcbnew.FromMM


# ------------------------------------------------------------------------------------------------ DRC helpers
def run_drc(board, report_path: str) -> List[str]:
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.WriteDRCReport(board, report_path, pcbnew.EDA_UNITS_MILLIMETRES, True)
    with open(report_path) as f:
        txt = f.read()
    return re.split(r"\n(?=\[)", txt)


def kinds(blocks) -> Counter:
    c = Counter()
    for b in blocks:
        m = re.match(r"\[(\w+)\]", b)
        if m:
            c[m.group(1)] += 1
    return c


ITEM = re.compile(r"@\(([\d.\-]+) mm, ([\d.\-]+) mm\): (Pad (\S+) \[([^\]]+)\] of (\S+) on ([\w.]+)|Track \[([^\]]+)\] on ([\w.]+)|Via \[([^\]]+)\]|Zone \[([^\]]+)\] on ([\w.]+))")


def unconnected(blocks):
    out = []
    for b in blocks:
        if not b.startswith("[unconnected_items]"):
            continue
        items = []
        for m in ITEM.finditer(b):
            x, y = float(m.group(1)), float(m.group(2))
            if m.group(4):
                items.append({"kind": "pad", "x": x, "y": y, "pad": m.group(4), "net": m.group(5), "ref": m.group(6),
                              "layer": m.group(7)})
            elif m.group(8):
                items.append({"kind": "track", "x": x, "y": y, "net": m.group(8), "layer": m.group(9)})
            elif m.group(10):
                items.append({"kind": "via", "x": x, "y": y, "net": m.group(10)})
            else:
                items.append({"kind": "zone", "x": x, "y": y, "net": m.group(11), "layer": m.group(12)})
        if items:
            out.append(items)
    return out


# ------------------------------------------------------------------------------------------------ geometry
def copper_layers(board):
    return [l for l in range(pcbnew.PCB_LAYER_ID_COUNT) if pcbnew.IsCopperLayer(l) and board.IsLayerEnabled(l)]


def _circle(cx, cy, r, n=20):
    return np.array([(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)])


def _capsule(a, b, r, n=10):
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    pts = []
    for cx, cy, a0 in ((b[0], b[1], ang - math.pi / 2), (a[0], a[1], ang + math.pi / 2)):
        for k in range(n + 1):
            t = a0 + math.pi * k / n
            pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return np.array(pts)


def _poly_points(item, layer, clearance):
    if isinstance(item, pcbnew.PCB_VIA):
        c = item.GetPosition()
        return [_circle(c.x, c.y, item.GetWidth() / 2 + clearance)]
    if isinstance(item, pcbnew.PCB_TRACK):
        a, b = item.GetStart(), item.GetEnd()
        return [_capsule((a.x, a.y), (b.x, b.y), item.GetWidth() / 2 + clearance)]
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, int(clearance), MM(0.005))
    polys = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        polys.append(np.array([(o.CPoint(k).x, o.CPoint(k).y) for k in range(o.PointCount())], dtype=float))
    return polys


class Grid:
    def __init__(self, board, net_name: str, res_mm=0.05, width_mm=0.2, clearance_mm=0.13, via_d=0.6, via_h=0.3,
                 edge_mm=0.3):
        from matplotlib.path import Path
        self.b = board
        self.res = MM(res_mm)
        bb = board.GetBoardEdgesBoundingBox()
        self.x0, self.y0 = bb.GetLeft(), bb.GetTop()
        self.nx = int(bb.GetWidth() / self.res) + 1
        self.ny = int(bb.GetHeight() / self.res) + 1
        self.layers = copper_layers(board)
        self.width, self.via_d, self.via_h = MM(width_mm), MM(via_d), MM(via_h)
        # signal nets: 0.15 mm; supply nets: 0.25 mm (a finishing stub, not the main feed)
        power = re.match(r"^(\+|.*/\+|.*VBUS|.*VBAT|GND$)", net_name) is not None
        self.width = MM(0.25) if power else MM(0.15)
        clr = MM(clearance_mm)
        netcode = board.GetNetcodeFromNetname(net_name)
        self.netcode = netcode
        xs = self.x0 + np.arange(self.nx) * self.res
        ys = self.y0 + np.arange(self.ny) * self.res
        self.block = {}      # layer -> bool[ny, nx] (track centreline forbidden)
        self.vblock = np.zeros((self.ny, self.nx), bool)
        items = [p for p in board.GetPads()] + [t for t in board.GetTracks()]
        # clearance between two items is the larger of their netclass clearances (patterns resolved by KiCad)
        ns = board.GetDesignSettings().m_NetSettings
        cache = {}

        def cls_clr(name):
            if name not in cache:
                try:
                    cache[name] = ns.GetEffectiveNetClass(name).GetClearance()
                except Exception:
                    cache[name] = clr
            return cache[name]
        own = max(cls_clr(net_name), clr)

        def item_clr(it):
            return max(own, cls_clr(it.GetNetname()))
        margin_t = self.width / 2 + own + MM(0.04)   # grid corner-cutting allowance
        margin_v = self.via_d / 2 + own + MM(0.04)

        def paint(arr, poly):
            x_lo, y_lo = poly.min(0)
            x_hi, y_hi = poly.max(0)
            i0, i1 = max(0, int((x_lo - self.x0) / self.res) - 1), min(self.nx, int((x_hi - self.x0) / self.res) + 2)
            j0, j1 = max(0, int((y_lo - self.y0) / self.res) - 1), min(self.ny, int((y_hi - self.y0) / self.res) + 2)
            if i1 <= i0 or j1 <= j0:
                return
            gx, gy = np.meshgrid(xs[i0:i1], ys[j0:j1])
            inside = Path(poly).contains_points(np.c_[gx.ravel(), gy.ravel()]).reshape(gy.shape)
            arr[j0:j1, i0:i1] |= inside

        for l in self.layers:
            arr = np.zeros((self.ny, self.nx), bool)
            for it in items:
                if it.GetNetCode() == netcode and netcode > 0:
                    continue
                if not it.IsOnLayer(l):
                    continue
                extra = item_clr(it) - own
                for poly in _poly_points(it, l, margin_t + extra):
                    paint(arr, poly)
                for poly in _poly_points(it, l, margin_v + extra):
                    paint(self.vblock, poly)
            self.block[l] = arr
        # no vias inside SMD pads of any net (solder would wick into the hole)
        for pd in board.GetPads():
            if pd.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                for l in (pcbnew.F_Cu, pcbnew.B_Cu):
                    if pd.IsOnLayer(l):
                        for poly in _poly_points(pd, l, self.via_d / 2 + MM(0.05)):
                            paint(self.vblock, poly)
                        break
        # holes of other nets (hole-to-hole) and the board edge
        for it in items:
            if isinstance(it, pcbnew.PCB_VIA) or (isinstance(it, pcbnew.PAD) and it.GetDrillSizeX() > 0):
                c = it.GetPosition()          # hole-to-hole applies to every net, own included
                d = (it.GetDrill() if isinstance(it, pcbnew.PCB_VIA) else it.GetDrillSizeX())
                r = (d + self.via_h) / 2 + MM(0.25)
                n = 24
                paint(self.vblock, np.array([(c.x + r * math.cos(2 * math.pi * k / n), c.y + r * math.sin(2 * math.pi * k / n))
                                             for k in range(n)]))
        e = int((MM(edge_mm) + self.width / 2) / self.res) + 1
        ev = int((MM(edge_mm) + self.via_d / 2) / self.res) + 1
        for arr in self.block.values():
            arr[:e, :] = arr[-e:, :] = True
            arr[:, :e] = arr[:, -e:] = True
        self.vblock[:ev, :] = self.vblock[-ev:, :] = True
        self.vblock[:, :ev] = self.vblock[:, -ev:] = True

    def cell(self, x, y):
        return int(round((y - self.y0) / self.res)), int(round((x - self.x0) / self.res))

    def xy(self, j, i):
        return int(self.x0 + i * self.res), int(self.y0 + j * self.res)

    def cells_in(self, item, layer):
        from matplotlib.path import Path
        out = []
        for poly in _poly_points(item, layer, 0):
            x_lo, y_lo = poly.min(0)
            x_hi, y_hi = poly.max(0)
            p = Path(poly)
            for j in range(int((y_lo - self.y0) / self.res), int((y_hi - self.y0) / self.res) + 2):
                for i in range(int((x_lo - self.x0) / self.res), int((x_hi - self.x0) / self.res) + 2):
                    x, y = self.xy(j, i)
                    if 0 <= j < self.ny and 0 <= i < self.nx and p.contains_point((x, y)):
                        out.append((j, i))
        return out


def astar(g: Grid, starts, goals, layer_cost, via_cost=40, max_nodes=4_000_000):
    """starts/goals: sets of (layer, j, i). Cells inside a start/goal pad are free even if near same-pad copper."""
    goal_set = set(goals)
    gl = np.array([(j, i) for _, j, i in goals])

    def h(j, i):
        d = np.abs(gl - (j, i)).min(0) if len(gl) else (0, 0)
        return int(np.min(np.abs(gl[:, 0] - j) + np.abs(gl[:, 1] - i)))

    openh = []
    best = {}
    parent = {}
    for s in starts:
        best[s] = 0
        heapq.heappush(openh, (h(s[1], s[2]), 0, s))
    free_cells = set(starts) | goal_set
    moves = [(0, 1, 10), (0, -1, 10), (1, 0, 10), (-1, 0, 10), (1, 1, 14), (1, -1, 14), (-1, 1, 14), (-1, -1, 14)]
    n = 0
    while openh:
        f, cost, node = heapq.heappop(openh)
        if node in goal_set:
            path = [node]
            while path[-1] in parent:
                path.append(parent[path[-1]])
            return path[::-1]
        if cost > best.get(node, 1e18):
            continue
        n += 1
        if n > max_nodes:
            return None
        l, j, i = node
        for dj, di, c in moves:
            nj, ni = j + dj, i + di
            if not (0 <= nj < g.ny and 0 <= ni < g.nx):
                continue
            nn = (l, nj, ni)
            if g.block[l][nj, ni] and nn not in free_cells:
                continue
            nc = cost + c * layer_cost[l]
            if nc < best.get(nn, 1e18):
                best[nn] = nc
                parent[nn] = node
                heapq.heappush(openh, (nc + 10 * h(nj, ni), nc, nn))
        if not g.vblock[j, i]:
            for l2 in g.layers:
                if l2 == l:
                    continue
                nn = (l2, j, i)
                if g.block[l2][j, i] and nn not in free_cells:
                    continue
                nc = cost + via_cost * 10
                if nc < best.get(nn, 1e18):
                    best[nn] = nc
                    parent[nn] = node
                    heapq.heappush(openh, (nc + 10 * h(j, i), nc, nn))
    return None


def commit_path(board, g: Grid, path) -> List:
    """Turn a cell path into straight segments + vias."""
    added = []
    # compress collinear runs
    pts = [path[0]]
    for a, b, c in zip(path, path[1:], path[2:]):
        if a[0] == b[0] == c[0] and (b[1] - a[1], b[2] - a[2]) == (c[1] - b[1], c[2] - b[2]):
            continue
        pts.append(b)
    pts.append(path[-1])
    for a, b in zip(pts, pts[1:]):
        if a[0] != b[0]:
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(*g.xy(a[1], a[2])))
            via.SetWidth(g.via_d)
            via.SetDrill(g.via_h)
            via.SetNetCode(g.netcode)
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            board.Add(via)
            added.append(via)
            continue
        if (a[1], a[2]) == (b[1], b[2]):
            continue
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(*g.xy(a[1], a[2])))
        t.SetEnd(pcbnew.VECTOR2I(*g.xy(b[1], b[2])))
        t.SetWidth(g.width)
        t.SetLayer(a[0])
        t.SetNetCode(g.netcode)
        board.Add(t)
        added.append(t)
    return added


def _items_at(board, it):
    """The pcbnew object(s) a DRC report item refers to."""
    if it["kind"] == "pad":
        fp = board.FindFootprintByReference(it["ref"])
        return [p for p in fp.Pads() if p.GetNumber() == it["pad"]]
    x, y = MM(it["x"]), MM(it["y"])
    net = board.GetNetcodeFromNetname(it["net"])
    best = []
    for t in board.GetTracks():
        if t.GetNetCode() != net:
            continue
        if isinstance(t, pcbnew.PCB_VIA):
            if it["kind"] == "via" and abs(t.GetPosition().x - x) < 2000 and abs(t.GetPosition().y - y) < 2000:
                best.append(t)
        elif it["kind"] == "track":
            a, e = t.GetStart(), t.GetEnd()
            dx, dy = e.x - a.x, e.y - a.y
            L2 = dx * dx + dy * dy
            u = 0 if L2 == 0 else max(0.0, min(1.0, ((x - a.x) * dx + (y - a.y) * dy) / L2))
            if math.hypot(a.x + u * dx - x, a.y + u * dy - y) < 5000:
                best.append(t)
    return best


def connected_cluster(board, item):
    """All same-net copper connected to item (KiCad connectivity)."""
    board.BuildConnectivity()
    conn = board.GetConnectivity()
    out = [item]
    try:
        for c in conn.GetConnectedItems(item, [pcbnew.PCB_PAD_T, pcbnew.PCB_TRACE_T, pcbnew.PCB_VIA_T,
                                               pcbnew.PCB_ARC_T]):
            out.append(c)
    except Exception:
        pass
    return out


def route_pair(board, a, b, layer_cost=None) -> Optional[List]:
    net = a["net"]
    g = Grid(board, net)
    lc = layer_cost or {l: (1 if l in (pcbnew.F_Cu, pcbnew.B_Cu) else 3) for l in g.layers}

    def endpoint_cells(it):
        cells = set()
        for obj in _items_at(board, it):
            for o in connected_cluster(board, obj):
                for l in g.layers:
                    if o.IsOnLayer(l) and (isinstance(o, pcbnew.PAD) or isinstance(o, pcbnew.PCB_VIA) or
                                           o.GetLayer() == l):
                        for j, i in g.cells_in(o, l):
                            cells.add((l, j, i))
        return cells

    sa, sb = endpoint_cells(a), endpoint_cells(b)
    if not sa or not sb:
        return None
    path = astar(g, sa, sb, lc)
    if not path:
        return None
    return commit_path(board, g, path)


def rip_up_near(board, pair, radius_mm=1.2) -> List:
    net = board.GetNetcodeFromNetname(pair[0]["net"])
    pts = []
    for it in pair:
        for o in _items_at(board, it):
            if isinstance(o, pcbnew.PAD):
                pts.append((o.GetPosition(), o))
    r = MM(radius_mm)
    out = []
    for t in list(board.GetTracks()):
        if t.GetNetCode() == net:
            continue
        if isinstance(t, pcbnew.PCB_VIA):
            if any(math.hypot(t.GetPosition().x - c.x, t.GetPosition().y - c.y) < r for c, _ in pts):
                out.append(t)
            continue
        a, e = t.GetStart(), t.GetEnd()
        for c, pad in pts:
            if not t.IsOnLayer(pcbnew.F_Cu if pad.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu):
                continue
            dx, dy = e.x - a.x, e.y - a.y
            L2 = dx * dx + dy * dy
            u = 0 if L2 == 0 else max(0.0, min(1.0, ((c.x - a.x) * dx + (c.y - a.y) * dy) / L2))
            if math.hypot(a.x + u * dx - c.x, a.y + u * dy - c.y) < r:
                out.append(t)
                break
    for t in out:
        board.Remove(t)
    return out


def plane_connect(board, obj, net_name: str) -> Optional[List]:
    """Connect a plane-net item (pad or track fragment) to its plane: shortest stub on its layer to the nearest spot
    where a via fits, then the via."""
    g = Grid(board, net_name)
    layer = obj.GetLayer() if not isinstance(obj, pcbnew.PAD) else (pcbnew.F_Cu if obj.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu)
    starts = [(layer, j, i) for j, i in g.cells_in(obj, layer)]
    if not starts:
        return None
    blk = g.block[layer]
    dist = {s: 0 for s in starts}
    parent = {}
    h = [(0, s) for s in starts]
    heapq.heapify(h)
    free = set(starts)
    while h:
        d, node = heapq.heappop(h)
        if d > dist[node]:
            continue
        l, j, i = node
        if not g.vblock[j, i] and d > 0:
            path = [node]
            while path[-1] in parent:
                path.append(parent[path[-1]])
            path = path[::-1]
            added = commit_path(board, g, path) if len(path) > 1 else []
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(*g.xy(j, i)))
            via.SetWidth(g.via_d)
            via.SetDrill(g.via_h)
            via.SetNetCode(g.netcode)
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            board.Add(via)
            return added + [via]
        if d > 800:           # 4 mm
            continue
        for dj, di, c in ((0, 1, 10), (0, -1, 10), (1, 0, 10), (-1, 0, 10), (1, 1, 14), (1, -1, 14), (-1, 1, 14), (-1, -1, 14)):
            nj, ni = j + dj, i + di
            if not (0 <= nj < g.ny and 0 <= ni < g.nx):
                continue
            nn = (l, nj, ni)
            if blk[nj, ni] and nn not in free:
                continue
            if d + c < dist.get(nn, 1e18):
                dist[nn] = d + c
                parent[nn] = node
                heapq.heappush(h, (d + c, nn))
    return None


# ------------------------------------------------------------------------------------------------ plane stitching
def stitch(board, pad, planes: Dict[str, List[str]], clearance_mm=0.16, via_d_mm=0.6):
    layer = pcbnew.F_Cu if pad.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
    net = pad.GetNetCode()
    obst = [p for p in board.GetPads() if p.GetNetCode() != net] + [t for t in board.GetTracks() if t.GetNetCode() != net]
    c = pad.GetPosition()
    half = max(pad.GetSize().x, pad.GetSize().y) / 2
    bb = board.GetBoardEdgesBoundingBox()
    clr = MM(clearance_mm)
    for dist in [half + MM(0.5) + MM(0.15) * k for k in range(10)]:
        for k in range(24):
            a = 2 * math.pi * k / 24
            pos = pcbnew.VECTOR2I(int(c.x + dist * math.cos(a)), int(c.y + dist * math.sin(a)))
            if not (bb.GetLeft() + MM(0.7) < pos.x < bb.GetRight() - MM(0.7) and
                    bb.GetTop() + MM(0.7) < pos.y < bb.GetBottom() - MM(0.7)):
                continue
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pos)
            via.SetWidth(MM(via_d_mm))
            via.SetDrill(MM(0.3))
            via.SetNetCode(net)
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            bad = False
            for l in copper_layers(board):
                s = via.GetEffectiveShape(l)
                if any(o.IsOnLayer(l) and s.Collide(o.GetEffectiveShape(l), clr) for o in obst):
                    bad = True
                    break
            if bad:
                continue
            if any((isinstance(o, pcbnew.PCB_VIA) or (isinstance(o, pcbnew.PAD) and o.GetDrillSizeX() > 0)) and
                   math.hypot(o.GetPosition().x - pos.x, o.GetPosition().y - pos.y) <
                   ((o.GetDrill() if isinstance(o, pcbnew.PCB_VIA) else o.GetDrillSizeX()) + MM(0.3)) / 2 + MM(0.25)
                   for o in obst):
                continue
            tr = pcbnew.PCB_TRACK(board)
            tr.SetStart(c)
            tr.SetEnd(pos)
            tr.SetWidth(MM(0.25))
            tr.SetLayer(layer)
            tr.SetNetCode(net)
            s = tr.GetEffectiveShape(layer)
            if any(o.IsOnLayer(layer) and s.Collide(o.GetEffectiveShape(layer), clr) for o in obst):
                continue
            board.Add(via)
            board.Add(tr)
            return [via, tr]
    return None


# ------------------------------------------------------------------------------------------------ driver
def finish(src: str, dst: str, planes: Dict[str, List[str]], report: str, rounds: int = 8, log=print) -> Dict:
    board = pcbnew.LoadBoard(src)
    added_by_us: List = []
    tried = set()
    tried_direct = set()
    history = []
    for rnd in range(rounds):
        blocks = run_drc(board, report)
        bad = [b for b in blocks if re.match(r"\[(clearance|hole_clearance|shorting_items|tracks_crossing|"
                                             r"copper_edge_clearance|hole_near_hole|holes_co_located)\]", b)]
        # take back our own additions that DRC rejects
        if bad and added_by_us:
            keep = []
            for obj in added_by_us:
                p = obj.GetPosition() if isinstance(obj, pcbnew.PCB_VIA) else obj.GetStart()
                tag = f"{pcbnew.ToMM(p.x):.4f} mm, {pcbnew.ToMM(p.y):.4f} mm"
                if any(tag in b for b in bad):
                    board.Remove(obj)
                else:
                    keep.append(obj)
            added_by_us = keep
        opens = unconnected(blocks)
        history.append({"round": rnd, "unconnected": len(opens), "violations": len(bad)})
        log(f"round {rnd}: {len(opens)} unconnected, {len(bad)} copper violations")
        if not opens:
            break
        progress = False
        for pair in opens:
            key = tuple(sorted((p.get("ref", ""), p.get("pad", ""), p["kind"], round(p["x"], 1), round(p["y"], 1))
                               for p in pair))
            if key in tried:
                continue
            tried.add(key)
            net = pair[0]["net"]
            pads = [p for p in pair if p["kind"] == "pad"]
            if net in planes:
                for p in pair:
                    if p["kind"] not in ("pad", "track"):
                        continue
                    objs = _items_at(board, p)
                    if not objs:
                        continue
                    got = ((stitch(board, objs[0], planes) or stitch(board, objs[0], planes, via_d_mm=0.5))
                           if p["kind"] == "pad" else None) or plane_connect(board, objs[0], net)
                    if got:
                        added_by_us += got
                        progress = True
                        log(f"  connected {p.get('ref', 'track')}.{p.get('pad', '')} ({net}) to its plane")
                if not progress and len(pair) == 2 and key not in tried_direct:
                    tried_direct.add(key)
                    got = route_pair(board, pair[0], pair[1])
                    if got:
                        added_by_us += got
                        progress = True
                        log(f"  joined two {net} islands directly")
                continue
            if len(pair) == 2 and all(p["kind"] in ("pad", "track", "via") for p in pair):
                got = route_pair(board, pair[0], pair[1])
                if not got:
                    # rip-up and retry: take out other nets' segments hugging the endpoints, route this net first,
                    # and let the next rounds re-route what was ripped
                    for radius in (1.2, 2.0, 3.0):
                        ripped = rip_up_near(board, pair, radius_mm=radius)
                        got = route_pair(board, pair[0], pair[1])
                        log(f"  ripped {len(ripped)} items within {radius} mm of {net} endpoints -> "
                            f"{'routed' if got else 'still blocked'}")
                        if got:
                            gone = {t.m_Uuid.AsString() for t in ripped}
                            added_by_us = [o for o in added_by_us if o.m_Uuid.AsString() not in gone]
                            break
                        for t in ripped:
                            board.Add(t)
                if got:
                    added_by_us += got
                    progress = True
                    log(f"  routed {net}: {len([o for o in got if isinstance(o, pcbnew.PCB_TRACK) and not isinstance(o, pcbnew.PCB_VIA)])} "
                        f"segments, {len([o for o in got if isinstance(o, pcbnew.PCB_VIA)])} vias")
                else:
                    log(f"  no path for {net}")
        if not progress and not bad:
            break
    blocks = run_drc(board, report)
    pcbnew.SaveBoard(dst, board)
    return {"out": dst, "history": history, "final": dict(kinds(blocks)), "open": unconnected(blocks)}


def _parse_planes(spec: List[str]) -> Dict[str, List[str]]:
    out = {}
    for s in spec:
        net, layers = s.split(":", 1)
        out[net] = layers.split(",")
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    planes = {"GND": ["In1.Cu", "B.Cu"], "+3V3": ["In2.Cu"]}
    if "--planes" in args:
        k = args.index("--planes")
        planes = _parse_planes(args[k + 1:])
        args = args[:k]
    import json
    r = finish(args[0], args[1], planes, args[2] if len(args) > 2 else "/tmp/finish_drc.rpt")
    print(json.dumps({k: v for k, v in r.items() if k != "open"}, indent=1))
    for o in r["open"]:
        print("OPEN:", o)


# ------------------------------------------------------------------------------------------------ negotiated routing
def _disk(r_cells):
    return [(dj, di) for dj in range(-r_cells, r_cells + 1) for di in range(-r_cells, r_cells + 1)
            if dj * dj + di * di <= r_cells * r_cells]


def negotiate(board, nets: List[str], center, radius_mm: float, iters: int = 40, log=print, via_d: float = 0.5,
              inner_cost: int = 2) -> Dict:
    """PathFinder-style negotiated congestion routing for a congested spot: rip the given nets' tracks and vias
    within radius of `center`, then route all their open connections together, letting nets compete for cells
    (present + history congestion costs) until no two nets overlap. Other copper stays fixed."""
    codes = {board.GetNetcodeFromNetname(n): n for n in nets}
    R = MM(radius_mm)
    rm = []
    for t in list(board.GetTracks()):
        if t.GetNetCode() not in codes:
            continue
        pts = [t.GetPosition()] if isinstance(t, pcbnew.PCB_VIA) else [t.GetStart(), t.GetEnd()]
        if any(math.hypot(p.x - center.x, p.y - center.y) < R for p in pts):
            rm.append(t)
    for t in rm:                 # remove after the scan (removing while iterating corrupts pcbnew's SWIG wrappers)
        board.Remove(t)
    negotiate._keep = rm
    blocks = run_drc(board, "/tmp/negotiate_drc.rpt")
    pairs = [p for p in unconnected(blocks) if p[0]["net"] in nets and len(p) == 2]
    grids, conns = {}, []
    for p in pairs:
        n = p[0]["net"]
        if n not in grids:
            grids[n] = Grid(board, n, via_d=via_d)
        g = grids[n]

        def cells(it):
            out = set()
            for obj in _items_at(board, it):
                for l in g.layers:
                    if obj.IsOnLayer(l) and (isinstance(obj, (pcbnew.PAD, pcbnew.PCB_VIA)) or obj.GetLayer() == l):
                        out |= {(l, j, i) for j, i in g.cells_in(obj, l)}
            return out
        a, b = cells(p[0]), cells(p[1])
        if a and b:
            conns.append((n, a, b))
    if not conns:
        return {"routed": 0, "pairs": 0}
    any_g = next(iter(grids.values()))
    res = any_g.res
    w, clr, vd = any_g.width, MM(0.145), any_g.via_d
    rc = lambda d: int(math.ceil(d / res))
    # footprints a path leaves for OTHER nets: where their track centrelines / via centres may not go
    tr_for_tr, tr_for_via = _disk(rc(w + clr)), _disk(rc(w / 2 + vd / 2 + clr))
    via_for_tr, via_for_via = _disk(rc(vd / 2 + w / 2 + clr)), _disk(rc(vd + clr + MM(0.05)))
    hist: Dict = {}
    pfac = 0.5
    layers = any_g.layers
    lcost = {l: (1 if l in (pcbnew.F_Cu, pcbnew.B_Cu) else 4) for l in layers}
    paths = {}

    L = len(layers)
    li = {l: k for k, l in enumerate(layers)}
    ny, nx = any_g.ny, any_g.nx

    def stamp(arr2d, j, i, disk_r):
        r = disk_r
        j0, j1, i0, i1 = max(0, j - r), min(ny, j + r + 1), max(0, i - r), min(nx, i + r + 1)
        yy, xx = np.ogrid[j0 - j:j1 - j, i0 - i:i1 - i]
        arr2d[j0:j1, i0:i1] |= (yy * yy + xx * xx) <= r * r

    R_tt, R_tv = rc(w + clr), rc(w / 2 + vd / 2 + clr)
    R_vt, R_vv = rc(vd / 2 + w / 2 + clr), rc(vd + clr + MM(0.05))

    def footprints(path):
        ft = np.zeros((L, ny, nx), bool)
        fv = np.zeros((ny, nx), bool)
        tc = np.zeros((L, ny, nx), bool)
        vc = np.zeros((ny, nx), bool)
        for idx, (l, j, i) in enumerate(path):
            via_here = idx + 1 < len(path) and path[idx + 1][0] != l
            if via_here:
                vc[j, i] = True
                tmp = np.zeros((ny, nx), bool)
                stamp(tmp, j, i, R_vt)
                ft |= tmp[None, :, :]
                stamp(fv, j, i, R_vv)
            else:
                tc[li[l], j, i] = True
                stamp(ft[li[l]], j, i, R_tt)
                stamp(fv, j, i, R_tv)
        return ft, fv, tc, vc

    # search window: the rip radius plus a margin around the congested spot (and every endpoint)
    cj, ci = any_g.cell(center.x, center.y)
    m = rc(R + MM(2.5))
    allc = [c for _, a, b in conns for c in list(a) + list(b)]
    win = (max(0, min([cj - m] + [c[1] - 10 for c in allc])), min(ny, max([cj + m] + [c[1] + 10 for c in allc])),
           max(0, min([ci - m] + [c[2] - 10 for c in allc])), min(nx, max([ci + m] + [c[2] + 10 for c in allc])))
    hist_t = np.zeros((L, ny, nx), np.float32)
    hist_v = np.zeros((ny, nx), np.float32)
    for it in range(iters):
        for k, (n, a, b) in enumerate(conns):
            ot = np.zeros((L, ny, nx), np.int16)
            ov = np.zeros((ny, nx), np.int16)
            for k2, pth in paths.items():
                if conns[k2][0] == n:
                    continue
                ot += pth["ft"]
                ov += pth["fv"]
            path = _astar_np(grids[n], a, b, lcost, li, ot, ov, hist_t, hist_v, pfac, win=win)
            if path is None:
                log(f"  negotiate: no path for {n}")
                paths.pop(k, None)
                continue
            ft, fv, tc, vc = footprints(path)
            paths[k] = {"cells": path, "ft": ft, "fv": fv, "tc": tc, "vc": vc}
        clash = 0
        for k, pth in paths.items():
            for k2, p2 in paths.items():
                if conns[k2][0] == conns[k][0]:
                    continue
                bt = pth["tc"] & p2["ft"]
                bv = pth["vc"] & p2["fv"]
                clash += int(bt.sum() + bv.sum())
                hist_t += bt
                hist_v += bv
        log(f"  negotiate iter {it}: {len(paths)}/{len(conns)} routed, {clash} conflicting cells")
        if clash == 0 and len(paths) == len(conns):
            break
        pfac *= 1.5
    added = []
    for k, pth in paths.items():
        added += commit_path(board, grids[conns[k][0]], pth["cells"])
    return {"routed": len(paths), "pairs": len(conns), "added": added}


def _astar_cost(g: Grid, starts, goals, lcost, ot, ov, hist, pfac, via_cost=40, max_nodes=3_000_000):
    goal_set = set(goals)
    gl = np.array([(j, i) for _, j, i in goals])

    def h(j, i):
        return int(np.min(np.abs(gl[:, 0] - j) + np.abs(gl[:, 1] - i))) * 10

    best, parent, openh = {}, {}, []
    for s in starts:
        best[s] = 0
        heapq.heappush(openh, (h(s[1], s[2]), 0, s))
    free = set(starts) | goal_set
    moves = [(0, 1, 10), (0, -1, 10), (1, 0, 10), (-1, 0, 10), (1, 1, 14), (1, -1, 14), (-1, 1, 14), (-1, -1, 14)]
    n = 0
    while openh:
        f, cost, node = heapq.heappop(openh)
        if node in goal_set:
            path = [node]
            while path[-1] in parent:
                path.append(parent[path[-1]])
            return path[::-1]
        if cost > best.get(node, 1e18):
            continue
        n += 1
        if n > max_nodes:
            return None
        l, j, i = node
        cand = []
        for dj, di, c in moves:
            nj, ni = j + dj, i + di
            if 0 <= nj < g.ny and 0 <= ni < g.nx:
                nn = (l, nj, ni)
                pen = (1 + hist.get(nn, 0)) * (1 + pfac * 20 * ot.get(nn, 0))
                cand.append((nn, c * lcost[l] * pen))
        if not g.vblock[j, i]:
            pen = (1 + hist.get((None, j, i), 0)) * (1 + pfac * 20 * ov.get((j, i), 0))
            for l2 in g.layers:
                if l2 != l:
                    cand.append(((l2, j, i), via_cost * 10 * pen))
        for nn, c in cand:
            if g.block[nn[0]][nn[1], nn[2]] and nn not in free:
                continue
            nc = cost + c
            if nc < best.get(nn, 1e18):
                best[nn] = nc
                parent[nn] = node
                heapq.heappush(openh, (nc + h(nn[1], nn[2]), nc, nn))
    return None


def _astar_np(g: Grid, starts, goals, lcost, li, ot, ov, hist_t, hist_v, pfac, via_cost=40, max_nodes=600_000, win=None):
    goal_set = set(goals)
    gl = np.array([(j, i) for _, j, i in goals])
    gj, gi = gl[:, 0], gl[:, 1]

    def h(j, i):
        return int(np.min(np.abs(gj - j) + np.abs(gi - i))) * 10

    best, parent, openh = {}, {}, []
    for s in starts:
        best[s] = 0
        heapq.heappush(openh, (h(s[1], s[2]), 0, s))
    free = set(starts) | goal_set
    moves = ((0, 1, 10), (0, -1, 10), (1, 0, 10), (-1, 0, 10), (1, 1, 14), (1, -1, 14), (-1, 1, 14), (-1, -1, 14))
    n = 0
    while openh:
        f, cost, node = heapq.heappop(openh)
        if node in goal_set:
            path = [node]
            while path[-1] in parent:
                path.append(parent[path[-1]])
            return path[::-1]
        if cost > best.get(node, 1e18):
            continue
        n += 1
        if n > max_nodes:
            return None
        l, j, i = node
        k = li[l]
        blk = g.block[l]
        for dj, di, c in moves:
            nj, ni = j + dj, i + di
            if not (0 <= nj < g.ny and 0 <= ni < g.nx):
                continue
            if win and not (win[0] <= nj < win[1] and win[2] <= ni < win[3]):
                continue
            nn = (l, nj, ni)
            if blk[nj, ni] and nn not in free:
                continue
            nc = cost + c * lcost[l] * (1 + hist_t[k, nj, ni]) * (1 + pfac * 20 * ot[k, nj, ni])
            if nc < best.get(nn, 1e18):
                best[nn] = nc
                parent[nn] = node
                heapq.heappush(openh, (nc + h(nj, ni), nc, nn))
        if not g.vblock[j, i]:
            vc = via_cost * 10 * (1 + hist_v[j, i]) * (1 + pfac * 20 * ov[j, i])
            for l2 in g.layers:
                if l2 == l:
                    continue
                nn = (l2, j, i)
                if g.block[l2][j, i] and nn not in free:
                    continue
                nc = cost + vc
                if nc < best.get(nn, 1e18):
                    best[nn] = nc
                    parent[nn] = node
                    heapq.heappush(openh, (nc + h(j, i), nc, nn))
    return None
