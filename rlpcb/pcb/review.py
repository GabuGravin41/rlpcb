"""Layout review: placement, routing and EMC advice for a board, with the reason behind each point, and a side-by-side
comparison of two layouts (for routing or placement studies).

These are design-review heuristics of the kind a senior layout engineer applies by eye (return paths, loop areas,
pair matching, protection at the connector, decoupling distance). They are labelled as such: each point carries a
`basis` ("measured" when it is a number taken from the board, "rule of thumb" when it is judgement), so the engineer
knows which ones to trust and which to verify. No field solver is involved.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ..design.verify import classify_net
from .board import Board

HS_RE = re.compile(r"(USB|D[+-]$|_?DP$|_?DM$|CLK|SCK|SCLK|SDIO|ETH|RMII|RGMII|MII|HDMI|LVDS|MIPI|PCIE|SWCLK|QSPI|"
                   r"OSC|XTAL|MCO)", re.I)
SW_RE = re.compile(r"(^|[_/])(SW|LX|PH|SW_NODE|BUCK_SW|BOOST_SW)\d*$", re.I)
PAIRS = [(r"(.*?)(DP|D\+|_P|\+)$", r"\1{}"), ]


def _base(n: str) -> str:
    return n.split("/")[-1]


def net_kind(name: str, declared: str = "") -> str:
    b = _base(name)
    if not name or name.startswith("unconnected"):
        return "nc"
    if declared in ("high_speed", "diff_pair", "rf"):
        return "high_speed"
    if SW_RE.search(b):
        return "switching"
    k = classify_net(name, declared if declared in ("power", "ground") else "")
    if k in ("power", "ground"):
        return k
    if HS_RE.search(b):
        return "high_speed"
    return "signal"


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _mst(points: List[Tuple[float, float]]) -> float:
    """Length of the minimum spanning tree over points (Prim, O(n²); fine for pads of one net)."""
    if len(points) < 2:
        return 0.0
    inside = [False] * len(points)
    best = [math.inf] * len(points)
    best[0] = 0.0
    total = 0.0
    for _ in points:
        i = min((k for k in range(len(points)) if not inside[k]), key=lambda k: best[k])
        inside[i] = True
        total += best[i]
        for j in range(len(points)):
            if not inside[j]:
                d = _dist(points[i], points[j])
                if d < best[j]:
                    best[j] = d
    return total


def pairs_of(nets: List[str]) -> List[Tuple[str, str]]:
    """Differential pairs by name: X_P/X_N, XP/XM, D+/D-, DP/DM."""
    s = set(nets)
    out = []
    for n in nets:
        b = n
        for pos, neg in (("_P", "_N"), ("DP", "DM"), ("D+", "D-"), ("+", "-"), ("P", "N")):
            if b.endswith(pos):
                m = b[: -len(pos)] + neg
                if m in s and (n, m) not in out:
                    if pos in ("P", "+") and not HS_RE.search(_base(n)):
                        continue
                    out.append((n, m))
                break
    return out


def layout_metrics(board: Board, plan=None) -> Dict:
    declared = {n.name: n.net_class for n in plan.nets} if plan else {}
    by_net_len: Dict[str, float] = defaultdict(float)
    by_net_layers: Dict[str, set] = defaultdict(set)
    by_layer: Dict[str, float] = defaultdict(float)
    for t in board.tracks:
        L = math.hypot(t.x2 - t.x1, t.y2 - t.y1)
        by_net_len[t.net] += L
        by_net_layers[t.net].add(t.layer)
        by_layer[t.layer] += L
    vias_by_net: Dict[str, int] = defaultdict(int)
    for v in board.vias:
        vias_by_net[v.net] += 1
    pads_by_net: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    for f in board.footprints:
        for p in f.pads:
            if p.net and not p.net.startswith("unconnected"):
                pads_by_net[p.net].append((p.x, p.y))
    rats = 0.0
    for n, pts in pads_by_net.items():
        if net_kind(n, declared.get(_base(n), "")) == "ground":
            continue                                    # ground goes to the plane, not along a ratsnest
        rats += _mst(pts)
    rs = board.routing_status()
    crit = {}
    for n in sorted(set(by_net_len) | set(pads_by_net)):
        k = net_kind(n, declared.get(_base(n), ""))
        if k in ("high_speed", "switching"):
            crit[n] = {"kind": k, "length_mm": round(by_net_len.get(n, 0.0), 2), "vias": vias_by_net.get(n, 0),
                       "layers": sorted(by_net_layers.get(n, []))}
    skew = {}
    for a, b in pairs_of(list(pads_by_net)):
        la, lb = by_net_len.get(a, 0.0), by_net_len.get(b, 0.0)
        if la or lb:
            skew[f"{_base(a)}/{_base(b)}"] = {"skew_mm": round(abs(la - lb), 2), "lengths_mm": [round(la, 2), round(lb, 2)],
                                              "vias": [vias_by_net.get(a, 0), vias_by_net.get(b, 0)]}
    return {"track_length_mm": round(sum(by_layer.values()), 1), "by_layer_mm": {k: round(v, 1) for k, v in by_layer.items()},
            "vias": len(board.vias), "unrouted": int(rs.get("unrouted_connections_approx", 0) or 0),
            "ratsnest_mm": round(rats, 1), "critical_nets": crit, "pairs": skew,
            "footprints": len(board.footprints),
            "bottom_side_parts": sum(1 for f in board.footprints if f.layer.startswith("B"))}


# --------------------------------------------------------------------------------------------------- review
def _pt(level, category, message, why, basis="rule of thumb", refs=(), fix=""):
    d = {"level": level, "category": category, "message": message, "why": why, "basis": basis, "refs": list(refs)}
    if fix:
        d["suggestion"] = fix
    return d


def _plane_layers(board: Board) -> Dict[str, str]:
    """{copper layer: plane net} for layers carrying a zone over most of the board."""
    x0, y0, x1, y1 = board.board_bbox()
    area = max((x1 - x0) * (y1 - y0), 1e-6)
    out = {}
    for z in board.zones:
        if not z["bbox"] or not z["net"]:
            continue
        bx0, by0, bx1, by1 = z["bbox"]
        if (bx1 - bx0) * (by1 - by0) >= 0.6 * area:
            for L in z["layers"]:
                out.setdefault(L, z["net"])
    return out


def _usb_high_speed(plan) -> bool:
    """True when the plan says the USB link runs at high speed (480 Mb/s)."""
    if not plan:
        return False
    txt = " ".join([str(getattr(plan, "requirements", "") or "")] +
                   [f"{n.name} {n.notes or ''}" for n in plan.nets if "USB" in n.name.upper()]).upper()
    return bool(re.search(r"USB ?(2\.0 )?HS\b|HIGH[- ]SPEED USB|USB HIGH[- ]SPEED|480 ?MB", txt))


def _source_pads(pads) -> set:
    """Pads where a rail's current comes from: an inductor (switcher output), a battery/power connector, or a
    regulator's output pin. Indexes into pads."""
    src = {k for k, (ref, p) in enumerate(pads) if re.match(r"^L\d", ref)}
    if not src:
        src = {k for k, (ref, p) in enumerate(pads) if re.match(r"^(J|P|BT)\d", ref) and
               re.search(r"BAT|PWR|VIN|DC|POWER", (p.pinfunction or "") + " " + ref, re.I)}
    if not src:
        src = {k for k, (ref, p) in enumerate(pads) if re.search(r"^(V?OUT|SW)", p.pinfunction or "", re.I)}
    return src


def _sense_branches(board: Board, nets, branches: Optional[Dict] = None) -> set:
    """Indexes of tracks that only lead to resistor pads (dividers, sense taps, pull-ups): they carry no load current,
    so a thin track there is right. Found by cutting each track and looking at what is on the far side.
    When `branches` is given, it receives {track index: [refs downstream]} for tracks that feed only part of the net
    (the side away from the rail's source)."""
    out = set()
    pads_by_net = defaultdict(list)
    for f in board.footprints:
        for p in f.pads:
            if _base(p.net) in nets:
                pads_by_net[p.net].append((f.ref, p))
    for net in {t.net for t in board.tracks if _base(t.net) in nets}:
        tr = [(i, t) for i, t in enumerate(board.tracks) if t.net == net]
        vias = [v for v in board.vias if v.net == net]
        zones = [z for z in board.zones if z["net"] == net and z["bbox"]]
        pads = pads_by_net.get(net, [])
        # nodes: 0..len(tr)*2-1 track ends, then vias, pads, zones
        nE = len(tr) * 2
        nV, nP = len(vias), len(pads)
        pts = []
        for _, t in tr:
            pts += [(t.x1, t.y1, t.layer), (t.x2, t.y2, t.layer)]
        adj = defaultdict(set)

        def link(a, b):
            adj[a].add(b); adj[b].add(a)

        def on_pad(x, y, layer, p):
            w, h = (p.h, p.w) if int(round(p.angle)) % 180 == 90 else (p.w, p.h)
            return (layer in p.layers or "*.Cu" in p.layers or p.drill > 0) and abs(x - p.x) <= w / 2 + 0.02 and \
                abs(y - p.y) <= h / 2 + 0.02
        for a in range(nE):
            xa, ya, la = pts[a]
            for b2 in range(a + 1, nE):
                xb, yb, lb = pts[b2]
                if la == lb and abs(xa - xb) < 0.02 and abs(ya - yb) < 0.02:
                    link(a, b2)
            for k, v in enumerate(vias):
                if math.hypot(xa - v.x, ya - v.y) <= v.size / 2 + 0.02:
                    link(a, nE + k)
            for k, (_, p) in enumerate(pads):
                if on_pad(xa, ya, la, p):
                    link(a, nE + nV + k)
            for k, z in enumerate(zones):
                zx0, zy0, zx1, zy1 = z["bbox"]
                if la in z["layers"] and zx0 <= xa <= zx1 and zy0 <= ya <= zy1:
                    link(a, nE + nV + nP + k)
        for k, (_, p) in enumerate(pads):
            for kz, z in enumerate(zones):
                zx0, zy0, zx1, zy1 = z["bbox"]
                if zx0 <= p.x <= zx1 and zy0 <= p.y <= zy1 and set(z["layers"]) & set(p.layers):
                    link(nE + nV + k, nE + nV + nP + kz)
        for j in range(len(tr)):
            link(2 * j, 2 * j + 1)
        src = {nE + nV + k for k in _source_pads(pads)}
        for j, (ti, t) in enumerate(tr):
            # cut this track and collect what the far end reaches
            a0, a1 = 2 * j, 2 * j + 1
            seen = {a0}
            stack = [a1]
            far = {a1}
            while stack:
                u = stack.pop()
                for w in adj[u]:
                    if (u, w) in ((a1, a0), (a0, a1)) or w in far:
                        continue
                    far.add(w); stack.append(w)
            if a0 in far:
                continue                                # part of a loop: shares current, keep it
            for side in (far, None):
                if side is None:
                    seen = {a0}; stack = [a0]
                    while stack:
                        u = stack.pop()
                        for w in adj[u]:
                            if (u, w) in ((a1, a0), (a0, a1)) or w in seen:
                                continue
                            seen.add(w); stack.append(w)
                    side = seen
                refs = [pads[k - nE - nV][0] for k in side if nE + nV <= k < nE + nV + nP]
                if refs and all(re.match(r"^(R|TP)\d", r) for r in refs) and \
                        len(refs) < len(pads):
                    out.add(ti)
                    break
                if branches is not None and refs and src and not (side & src) and len(refs) < len(pads):
                    # a branch only if the current already split before it: some load sits on the source side
                    near = [pads[k][0] for k in range(nP) if (nE + nV + k) not in side and (nE + nV + k) not in src]
                    if any(not re.match(r"^(C|R|L|FB)\d", r) for r in near):
                        branches[ti] = sorted(set(refs))
    return out


def _current_points(board: Board, plan, kind) -> List[Dict]:
    """Track width against the current the plan gives each net (IPC-2221). Pours on the net count as wide copper."""
    from .ampacity import rise_for, width_for
    out: List[Dict] = []
    if not plan:
        return out
    cur = {n.name: n.current_a for n in plan.nets if n.current_a}
    if not cur:
        return out
    inner = set(board.copper_layers[1:-1])
    segs = defaultdict(list)
    branch: Dict[int, List[str]] = {}
    sense_only = _sense_branches(board, {k for k in cur}, branch)
    for i in list(branch):                              # a switch node has no branches: all of it carries the current
        if kind(board.tracks[i].net) == "switching":
            del branch[i]
    for i, t in enumerate(board.tracks):
        L = math.hypot(t.x2 - t.x1, t.y2 - t.y1)
        if L >= 0.5 and i not in sense_only:            # pad entries, zero-length stubs and sense taps carry no load
            segs[_base(t.net)].append((t.width, t.layer, L, branch.get(i)))
    for name, amps in sorted(cur.items()):
        if kind(name) == "ground" or name not in segs:
            continue
        # short necks at a pad (< 2 mm, at least 40 % of the 10 °C width) are cooled by the pad and the plane
        w10 = width_for(amps, 10)
        segs[name] = [sg for sg in segs[name] if not (sg[2] < 2.0 and sg[0] >= 0.4 * w10 * (2 if sg[1] in inner else 1))]
        if not segs[name]:
            continue
        rise = lambda sg: rise_for(amps, sg[0], inner=sg[1] in inner)
        trunk = [sg for sg in segs[name] if not sg[3]]
        brs = [sg for sg in segs[name] if sg[3]]
        # the trunk (between the source and the bulk of the load) carries the full current; a branch feeds only
        # the parts downstream of it, so it is judged and reported separately
        for sg in sorted(brs, key=rise, reverse=True)[:1]:
            if rise(sg) > 15:
                out.append(_pt("suggestion", "power",
                               f"{name}: branch to {', '.join(sg[3][:6])} is {sg[0]:.2f} mm ({sg[1]}); at the full "
                               f"{amps:g} A that would be about {rise(sg):.0f} °C rise",
                               "a branch carries only what the parts beyond it draw. If they draw well under the "
                               "rail's total this is fine; the plan gives one current per net, so check this branch "
                               "against what those parts need", "measured",
                               refs=sg[3][:6], fix=f"≥ {width_for(amps, 10):.2f} mm only if those parts draw the "
                                                   "full current"))
        if not trunk:
            continue
        worst = max(trunk, key=rise)
        w, layer = worst[0], worst[1]
        is_in = layer in inner
        dT = rise(worst)
        narrow = sum(sg[2] for sg in trunk if rise(sg) > 20)
        need = width_for(amps, 10, inner=is_in)
        lvl = "concern" if dT > 30 else ("suggestion" if dT > 15 else "good")
        msg = (f"{name}: {amps:g} A on {w:.2f} mm track ({layer}{', inner' if is_in else ''}) → about {dT:.0f} °C rise"
               if lvl != "good" else f"{name}: tracks are wide enough for {amps:g} A (≤ {dT:.0f} °C rise)")
        if lvl != "good" and narrow:
            msg += f"; {narrow:.0f} mm of the net is this narrow"
        out.append(_pt(lvl, "power", msg,
                       "IPC-2221 (1 oz copper): a track's temperature rise grows with current squared over its "
                       "cross-section; inner layers shed heat half as well. Above ~20–30 °C the copper ages the "
                       "board and drops voltage; far above it the track can fuse", "measured",
                       fix="" if lvl == "good" else f"widen to ≥ {need:.2f} mm{' on this inner layer' if is_in else ''} "
                                                    f"(10 °C rise), use a pour, or move it to an outer layer"))
    return out


def review_layout(board: Board, plan=None, focus: str = "all") -> Dict:
    """Design-review points for a board. focus: all | placement | routing | emc | power | dfm."""
    pts: List[Dict] = []
    declared = {n.name: n.net_class for n in plan.nets} if plan else {}
    kind = lambda n: net_kind(n, declared.get(_base(n), ""))
    m = layout_metrics(board, plan)
    x0, y0, x1, y1 = board.board_bbox()
    W, H = x1 - x0, y1 - y0
    fps = board.footprints
    cu = board.copper_layers
    planes = _plane_layers(board)

    # ---------------------------------------------------------------- stack-up / return paths (emc)
    for i, L in enumerate(cu):
        if L in planes:
            continue
        nbrs = [cu[j] for j in (i - 1, i + 1) if 0 <= j < len(cu)]
        refp = [(n, planes[n]) for n in nbrs if n in planes]
        hs_here = [n for n, c in m["critical_nets"].items() if L in c["layers"] and c["kind"] == "high_speed"]
        if refp:
            gnd = [n for n, net in refp if kind(net) == "ground"]
            if gnd:
                pts.append(_pt("good", "emc", f"{L} signals sit next to a ground plane ({gnd[0]})",
                               "return current flows in the plane directly under each track, so loops stay small",
                               "measured"))
            elif hs_here:
                pts.append(_pt("suggestion", "emc", f"{L} is referenced to a power plane ({refp[0][1]} on {refp[0][0]}), and "
                               f"fast nets run on it: {', '.join(_base(n) for n in hs_here[:5])}",
                               "the return current must cross to ground through decoupling capacitors; that works but adds "
                               "loop area. Keep fast signals on the layer next to ground, or put stitching capacitors near "
                               "where these signals change layer", refs=[]))
        elif hs_here and len(cu) > 2:
            pts.append(_pt("concern", "emc", f"fast nets on {L} have no adjacent plane: {', '.join(_base(n) for n in hs_here[:5])}",
                           "without a reference plane the return path is wherever it can find copper; loop area and "
                           "radiated emissions go up", fix=f"route these on a layer adjacent to a ground plane"))
    if len(cu) <= 2 and not planes:
        pts.append(_pt("concern", "emc", "2-layer board with no ground pour",
                       "every signal's return current must find its own way back; a solid ground pour on B.Cu is the "
                       "cheapest EMC improvement available", fix="pour GND on the bottom layer and keep it unbroken"))
    # ground stitching
    gnd_vias = sum(1 for v in board.vias if kind(v.net) == "ground")
    area_cm2 = W * H / 100.0
    gnd_layers = [L for L, n in planes.items() if kind(n) == "ground"]
    if len(gnd_layers) >= 2 and area_cm2 > 0:
        dens = gnd_vias / area_cm2
        if dens < 1.0:
            pts.append(_pt("suggestion", "emc", f"{gnd_vias} ground vias for {area_cm2:.1f} cm² ({dens:.1f}/cm²) joining "
                           f"ground on {', '.join(gnd_layers)}", "ground on several layers should be stitched every few "
                           "millimetres (and next to every signal via that changes reference), or the planes act as a "
                           "patch antenna at higher frequencies", "measured",
                           fix="add a ground via next to each signal via, and a row along the board edge"))
        else:
            pts.append(_pt("good", "emc", f"ground layers are stitched ({dens:.1f} vias/cm²)", "planes stay at one potential",
                           "measured"))

    # ---------------------------------------------------------------- pairs and fast nets (routing)
    hs_usb = _usb_high_speed(plan)
    for name, s in m["pairs"].items():
        usb = "USB" in name.upper()
        # USB 2.0 high speed (480 Mb/s): match within ~0.15 mm is the usual guide, > 1 mm is a real risk.
        # Full speed (12 Mb/s, e.g. STM32F4 OTG_FS): edges of 4–20 ns tolerate centimetres of skew; matching then
        # matters for emissions (common mode), not for the data.
        lim_s, lim_c = (0.15, 1.0) if (hs_usb or not usb) else (2.0, 25.0)
        if s["skew_mm"] > lim_s:
            lvl = "concern" if s["skew_mm"] > lim_c else "suggestion"
            why = ("skew turns part of the differential signal into common mode, which radiates. " +
                   ("At USB high speed it also closes the eye." if (usb and hs_usb) else
                    "At USB full speed (12 Mb/s) the data still arrives correctly, so this is about emissions only."
                    if usb else ""))
            pts.append(_pt(lvl, "routing", f"pair {name}: length mismatch {s['skew_mm']} mm ({s['lengths_mm']})",
                           why.strip(), "measured", fix="route the pair side by side, then add a small meander on the "
                                                        "shorter line next to where the mismatch starts"))
        elif s["lengths_mm"][0]:
            pts.append(_pt("good", "routing", f"pair {name} matched within {s['skew_mm']} mm", "low common-mode conversion",
                           "measured"))
        if s["vias"][0] != s["vias"][1]:
            pts.append(_pt("suggestion", "routing", f"pair {name} has unequal vias {s['vias']}",
                           "each via adds an impedance step; give both lines the same number, side by side", "measured"))
    for n, c in m["critical_nets"].items():
        if c["kind"] == "high_speed" and not n.endswith(("DM", "D-", "_N")):
            if c["vias"] > 2:
                pts.append(_pt("suggestion", "routing", f"{_base(n)}: {c['vias']} vias on a fast net",
                               "every layer change moves the return current to another plane; add a ground via beside "
                               "each one or keep the net on one layer", "measured"))
            if c["length_mm"] > 60:
                pts.append(_pt("suggestion", "routing", f"{_base(n)}: {c['length_mm']:.0f} mm long",
                               "long clock and data lines ring and radiate; shorten by moving the endpoints closer, or "
                               "add a 22–33 Ω series resistor at the driver", "measured"))

    # ---------------------------------------------------------------- current capacity (power)
    pts += _current_points(board, plan, kind)

    # ---------------------------------------------------------------- power: switching nodes, hot loops (power)
    pads_of = defaultdict(list)
    for f in fps:
        for p in f.pads:
            pads_of[p.net].append((f, p))
    for n, c in m["critical_nets"].items():
        if c["kind"] != "switching":
            continue
        pours = [z for z in board.zones if z["net"] == n and z["bbox"]]
        if pours:
            zx0, zy0, zx1, zy1 = pours[0]["bbox"]
            span = max(zx1 - zx0, zy1 - zy0)
            pts.append(_pt("good" if span <= 10 else "suggestion", "power",
                           f"switching node {_base(n)} is a copper pour {zx1 - zx0:.1f} × {zy1 - zy0:.1f} mm"
                           + (f" plus {c['length_mm']:.1f} mm of track" if c["length_mm"] > 0.5 else ""),
                           "a compact pour carries the current with a small radiating area", "measured"))
        elif c["length_mm"] > 8:
            pts.append(_pt("concern", "power", f"switching node {_base(n)}: {c['length_mm']:.1f} mm of track",
                           "the switch node swings the full input voltage at every edge; its copper is an antenna. Keep it "
                           "a short, wide stub between the regulator and the inductor", "measured", fix="move the inductor "
                           "right against the regulator's SW pin"))
        else:
            pts.append(_pt("good", "power", f"switching node {_base(n)} is short ({c['length_mm']:.1f} mm)",
                           "small radiating area", "measured"))
        # hot loop: regulator VIN pin to nearest input capacitor
        ics = {f.ref for f, p in pads_of[n] if re.match(r"^(U|IC)\d", f.ref)}
        for ref in ics:
            f = next(x for x in fps if x.ref == ref)
            vin = [p for p in f.pads if re.search(r"VIN|VCC|PVIN|VIN\d", p.pinfunction or "", re.I)]
            if not vin:
                # no pin names in the board file: the input is the IC's power pin that is not the inductor's output
                outs = {q.net for f2, q in pads_of[n] if re.match(r"^L\d", f2.ref)}
                outs = {q.net for f2 in fps if re.match(r"^L\d", f2.ref) and any(x.net == n for x in f2.pads)
                        for q in f2.pads} - {n}
                vin = [p for p in f.pads if kind(p.net) == "power" and p.net not in outs]
            for p in vin[:1]:
                caps = [(min(_dist((p.x, p.y), (q.x, q.y)) for q in c2.pads), c2.ref) for c2 in fps
                        if re.match(r"^C\d", c2.ref) and any(q.net == p.net for q in c2.pads)
                        and any(kind(q.net) == "ground" for q in c2.pads)]
                if caps:
                    d, cref = min(caps)
                    lvl = "concern" if d > 6 else ("suggestion" if d > 3 else "good")
                    pts.append(_pt(lvl, "power", f"{ref} input capacitor {cref} is {d:.1f} mm from the VIN pin",
                                   "the input capacitor closes the high-di/dt 'hot loop' of a buck converter; its area "
                                   "sets the ringing and the emissions more than anything else on the board", "measured",
                                   refs=[ref, cref], fix="" if lvl == "good" else f"put {cref} right at {ref} pin "
                                                                                    f"{p.number}, with ground vias at its "
                                                                                    "ground pad"))

    # ---------------------------------------------------------------- protection and connectors (placement)
    def edge_dist(f):
        return min(f.x - x0, x1 - f.x, f.y - y0, y1 - f.y)
    for f in fps:
        if not re.match(r"^(J|P|USB)\d", f.ref) or f.dnp:
            continue
        d = edge_dist(f)
        if d > 6 and len(f.pads) > 2:
            pts.append(_pt("suggestion", "placement", f"connector {f.ref} ({f.value}) sits {d:.1f} mm from the nearest edge",
                           "cables are easier to plug and strain-relieve at the edge, and the cable's noise stays out "
                           "of the board's middle", "measured", refs=[f.ref]))
    prot = [f for f in fps if re.search(r"USBLC|ESD|TVS|SMAJ|SMBJ|PESD|TPD\d|SP05|PRTR", f.value or "", re.I)]
    for pr in prot:
        nets = {p.net for p in pr.pads if p.net and kind(p.net) not in ("ground", "nc")}
        conns = [f for f in fps if re.match(r"^(J|P|USB)\d", f.ref) and nets & {p.net for p in f.pads}]
        for cn in conns:
            d = min(_dist((p.x, p.y), (q.x, q.y)) for p in pr.pads for q in cn.pads if p.net in nets and q.net == p.net)
            lvl = "concern" if d > 12 else ("suggestion" if d > 6 else "good")
            pts.append(_pt(lvl, "placement", f"protection {pr.ref} ({pr.value}) is {d:.1f} mm from {cn.ref}",
                           "an ESD or surge clamp works only if the strike reaches it before anything else; place it at "
                           "the connector, with a short, direct path to ground", "measured", refs=[pr.ref, cn.ref]))
    # decoupling summary (the individual warnings come from design_checks)
    ics = [f for f in fps if re.match(r"^(U|IC)\d", f.ref) and len(f.pads) >= 3]
    worst = []
    for c in fps:
        if not re.match(r"^C\d", c.ref) or len(c.pads) != 2:
            continue
        nets = [p.net for p in c.pads]
        if not any(kind(n) == "ground" for n in nets):
            continue
        pw = [n for n in nets if n and kind(n) == "power"]
        if not pw:
            continue
        best = None
        srcs = ics + [f for f in fps if re.match(r"^L\d", f.ref)]
        for ic in srcs:
            for p in ic.pads:
                if p.net == pw[0]:
                    d = min(_dist((p.x, p.y), (q.x, q.y)) for q in c.pads)
                    if best is None or d < best[0]:
                        best = (d, ic.ref)
        if best:
            worst.append((best[0], c.ref, best[1]))
    if worst:
        worst.sort(reverse=True)
        far = [w for w in worst if w[0] > 5]
        pts.append(_pt("concern" if far else "good", "power",
                       f"decoupling: {len(worst)} capacitors; farthest {worst[0][1]} is {worst[0][0]:.1f} mm from "
                       f"{worst[0][2]}" + (f"; {len(far)} beyond 5 mm" if far else ""),
                       "a decoupling capacitor only helps if the loop from it to the pin is small; beyond a few mm the "
                       "track inductance cancels it at the frequencies that matter", "measured",
                       refs=[w[1] for w in far[:6]]))
    # crystal: vias on oscillator nets
    for n, c in m["critical_nets"].items():
        if re.search(r"OSC|XTAL", _base(n), re.I) and c["vias"]:
            pts.append(_pt("suggestion", "routing", f"{_base(n)} changes layer ({c['vias']} vias)",
                           "crystal lines are high-impedance and pick up noise; keep them on one layer, short, with a "
                           "ground guard and no other signals under the crystal", "measured"))

    # ---------------------------------------------------------------- placement quality
    if m["unrouted"] and m["track_length_mm"] < 1:
        pts.append(_pt("info", "placement", f"placement wirelength (ratsnest) {m['ratsnest_mm']:.0f} mm",
                       "a shorter ratsnest usually routes more easily; compare alternative placements with "
                       "compare_layouts", "measured"))

    # ---------------------------------------------------------------- manufacturing (dfm)
    near_edge = [f.ref for f in fps if f.courtyard != (0, 0, 0, 0) and not re.match(r"^(J|P|H|MH)\d", f.ref)
                 and min(f.courtyard[0] - x0, x1 - f.courtyard[2], f.courtyard[1] - y0, y1 - f.courtyard[3]) < 0.3]
    if near_edge:
        pts.append(_pt("concern", "dfm", f"parts within 0.3 mm of the board edge: {', '.join(near_edge[:8])}",
                       "depanelisation (V-score or routing) can crack parts that close to the edge, especially ceramic "
                       "capacitors", "measured", refs=near_edge[:8]))
    if m["bottom_side_parts"]:
        bot = [f.ref for f in fps if f.layer.startswith("B") and not re.match(r"^(H|MH|TP)\d", f.ref)]
        if bot:
            pts.append(_pt("info", "dfm", f"{len(bot)} parts on the bottom side",
                           "double-sided assembly costs more and the second side's parts go through reflow twice; "
                           "worth it only if space requires it", "measured", refs=bot[:10]))
    holes = [f for f in fps if re.match(r"^(H|MH)\d", f.ref)]
    if not holes and W * H > 900:
        pts.append(_pt("suggestion", "dfm", "no mounting holes", "a board this size will need fixing in its enclosure; add "
                       "holes before routing, it is much harder afterwards"))
    if focus != "all":
        pts = [p for p in pts if p["category"] == focus]
    order = {"concern": 0, "suggestion": 1, "info": 2, "good": 3}
    pts.sort(key=lambda p: order[p["level"]])
    summary = {k: sum(1 for p in pts if p["level"] == k) for k in order}
    return {"summary": summary, "points": pts, "metrics": {k: m[k] for k in ("track_length_mm", "vias", "unrouted",
                                                                              "ratsnest_mm", "pairs")},
            "planes": planes,
            "basis": "rules of thumb from layout practice and measurements from the board file; no field simulation"}


def compare_layouts(a: Board, b: Board, plan=None, labels=("A", "B")) -> Dict:
    """Side-by-side numbers for two versions of a board, with a verdict per metric."""
    ma, mb = layout_metrics(a, plan), layout_metrics(b, plan)
    ra, rb = review_layout(a, plan), review_layout(b, plan)
    rows = []

    def row(name, va, vb, lower_better=True, unit=""):
        if va == vb:
            v = "same"
        elif (vb < va) == lower_better:
            v = labels[1]
        else:
            v = labels[0]
        rows.append({"metric": name, labels[0]: va, labels[1]: vb, "better": v, "unit": unit})
    row("unrouted connections", ma["unrouted"], mb["unrouted"])
    row("track length", ma["track_length_mm"], mb["track_length_mm"], unit="mm")
    row("vias", ma["vias"], mb["vias"])
    row("ratsnest (placement wirelength)", ma["ratsnest_mm"], mb["ratsnest_mm"], unit="mm")
    for k in sorted(set(ma["pairs"]) | set(mb["pairs"])):
        row(f"pair {k} skew", ma["pairs"].get(k, {}).get("skew_mm", 0), mb["pairs"].get(k, {}).get("skew_mm", 0), unit="mm")
    for n in sorted(set(ma["critical_nets"]) | set(mb["critical_nets"])):
        ca, cb = ma["critical_nets"].get(n, {}), mb["critical_nets"].get(n, {})
        if ca.get("kind") == "switching" or cb.get("kind") == "switching":
            row(f"switch node {_base(n)} length", ca.get("length_mm", 0), cb.get("length_mm", 0), unit="mm")
    row("review concerns", ra["summary"]["concern"], rb["summary"]["concern"])
    row("review suggestions", ra["summary"]["suggestion"], rb["summary"]["suggestion"])
    notes = ["fewer vias and shorter tracks are not automatically better: check the concerns and the pairs first"]
    if ma["unrouted"] != mb["unrouted"]:
        notes.insert(0, f"the two layouts are at different stages ({ma['unrouted']} vs {mb['unrouted']} unrouted "
                        "connections); copper totals are only comparable between complete layouts")
    wins = {labels[0]: sum(r["better"] == labels[0] for r in rows), labels[1]: sum(r["better"] == labels[1] for r in rows)}
    new_c = [p["message"] for p in rb["points"] if p["level"] == "concern"
             and p["message"] not in {q["message"] for q in ra["points"]}]
    gone_c = [p["message"] for p in ra["points"] if p["level"] == "concern"
              and p["message"] not in {q["message"] for q in rb["points"]}]
    return {"rows": rows, "wins": wins, "new_concerns_in_" + labels[1]: new_c, "concerns_fixed_in_" + labels[1]: gone_c,
            "notes": notes}
